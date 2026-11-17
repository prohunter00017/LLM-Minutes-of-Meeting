#!/usr/bin/env python3
"""Test updated Cloudflare provider with reasoning_content."""
import urllib.request
import json

# Simulated response from the error screenshot
simulated_result = {
    "success": True,
    "result": {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "## Meeting Summary\nTesting app functionality.\n\n## Attendees\nNot specified.\n\n## Key Discussion Points\n- Testing the app\n\n## Decisions Made\n1. None\n\n## Action Items\n| Task | Owner | Due Date |\n|------|-------|----------|\n| Test app | TBD | TBD |\n\n## Next Steps\nContinue testing."
            }
        }]
    }
}

# Test the extraction logic
result = simulated_result["result"]
choices = result.get("choices", [])
msg = choices[0]["message"]
content = msg.get("content", "")
if content:
    extracted = content
else:
    reasoning = msg.get("reasoning_content", "")
    if reasoning:
        extracted = reasoning
    else:
        extracted = "EMPTY"

print("Extracted content:")
print(extracted)
print(f"\nLength: {len(extracted)} chars")
print(f"Content was null: {msg['content'] is None}")
print(f"Reasoning present: {bool(msg.get('reasoning_content'))}")
