# RollWatch Integration Guide

This guide shows how to connect a managed microservice (such as a **Go** backend deployed via AWS ECR + EC2) to **RollWatch** for live version-drift detection, post-deploy SLO verification, and automated rollback.

---

## 1. Go `/health` Handler (Version-Aware)

Drop this 25-line handler into your Go service (`main.go` or `health.go`) and inject the commit hash at compile time using `-ldflags`:

```go
package main

import (
	"encoding/json"
	"net/http"
)

// Populated at build time: go build -ldflags="-X main.gitSHA=$(git rev-parse --short HEAD)"
var gitSHA = "dev"

func healthHandler(dbPing func() error) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		dbStatus, status, code := "ok", "ok", http.StatusOK
		if dbPing != nil && dbPing() != nil {
			dbStatus, status, code = "error", "degraded", http.StatusServiceUnavailable
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		_ = json.NewEncoder(w).Encode(map[string]string{
			"status":  status,
			"git_sha": gitSHA,
			"db":      dbStatus,
		})
	}
}
```

Build example in your service `Dockerfile`:

```dockerfile
ARG GIT_SHA=dev
RUN CGO_ENABLED=0 go build -ldflags="-s -w -X main.gitSHA=${GIT_SHA}" -o /app/server ./cmd/server
```

---

## 2. GitHub Actions Deploy Webhook Step

Add this step to your service's deploy workflow immediately after starting the new container on EC2/ECS. RollWatch will update `expected_git_sha`, probe `/health` every 5 seconds across `verify_window_sec`, and automatically roll back to `previous_image_tag` if p95 latency or error rate breaches your SLO:

```yaml
      - name: Notify RollWatch for Post-Deploy Verification
        env:
          ROLLWATCH_URL: ${{ secrets.ROLLWATCH_URL }}
          ROLLWATCH_WEBHOOK_SECRET: ${{ secrets.ROLLWATCH_WEBHOOK_SECRET }}
          ROLLWATCH_TARGET_ID: ${{ secrets.ROLLWATCH_TARGET_ID }}
          NEW_IMAGE_TAG: ${{ steps.deploy.outputs.new_image_tag }}
          PREVIOUS_IMAGE_TAG: ${{ steps.deploy.outputs.previous_image_tag }}
        run: |
          curl --fail-with-body -sS -X POST "${ROLLWATCH_URL}/api/webhooks/deploy" \
            -H "Content-Type: application/json" \
            -H "X-Webhook-Secret: ${ROLLWATCH_WEBHOOK_SECRET}" \
            -d "{
              \"target_id\": \"${ROLLWATCH_TARGET_ID}\",
              \"commit_sha\": \"${GITHUB_SHA}\",
              \"image_tag\": \"${NEW_IMAGE_TAG}\",
              \"previous_image_tag\": \"${PREVIOUS_IMAGE_TAG}\"
            }"
```

---

## 3. Minimal IAM Policy for AWS SSM Auto-Rollback

Attach this least-privilege IAM policy to the RollWatch IAM user or task role. It restricts `ssm:SendCommand` to **only** EC2 instances tagged with `RollWatchManaged=true` and only the `AWS-RunShellScript` document:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowRollWatchSendCommandOnTaggedInstance",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": [
        "arn:aws:ssm:us-east-1::document/AWS-RunShellScript"
      ]
    },
    {
      "Sid": "RestrictSendCommandToManagedEC2Tag",
      "Effect": "Allow",
      "Action": "ssm:SendCommand",
      "Resource": "arn:aws:ec2:us-east-1:123456789012:instance/*",
      "Condition": {
        "StringEquals": {
          "aws:ResourceTag/RollWatchManaged": "true"
        }
      }
    },
    {
      "Sid": "AllowReadCommandInvocationStatus",
      "Effect": "Allow",
      "Action": "ssm:GetCommandInvocation",
      "Resource": "arn:aws:ssm:us-east-1:123456789012:*"
    }
  ]
}
```

Replace `us-east-1` and `123456789012` with your target AWS region and account ID, and tag your EC2 host with `RollWatchManaged=true`.
