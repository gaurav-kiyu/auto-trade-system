# OPB FINAL CLOSURE — Environment and Test Report

## Dependency installation attempt

{
  "hypothesis": {
    "returncode": 1,
    "tail": "back (most recent call last):\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/patches/warm_spreadsheet_runtime_on_startup.py\", line 26, in warm_spreadsheet_runtime_on_startup\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 785, in warm_spreadsheet_runtime\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 720, in _warm_feature_flows\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 704, in _warm_collaboration_flows\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/generated/interface/models.py\", line 32317, in hydrate_crdt_from_proto\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/remote.py\", line 749, in __call__\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/client.py\", line 150, in call\nartifact_tool.rpc.client.RemoteError: hydrateCrdtFromProto requires an empty collaborative document.\n\u001b[31mERROR: Could not find a version that satisfies the requirement hypothesis (from versions: none)\u001b[0m\u001b[31m\n\u001b[0m\u001b[31mERROR: No matching distribution found for hypothesis\u001b[0m\u001b[31m\n\u001b[0m"
  },
  "duckdb": {
    "returncode": 1,
    "tail": "up\nTraceback (most recent call last):\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/patches/warm_spreadsheet_runtime_on_startup.py\", line 26, in warm_spreadsheet_runtime_on_startup\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 785, in warm_spreadsheet_runtime\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 720, in _warm_feature_flows\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 704, in _warm_collaboration_flows\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/generated/interface/models.py\", line 32317, in hydrate_crdt_from_proto\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/remote.py\", line 749, in __call__\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/client.py\", line 150, in call\nartifact_tool.rpc.client.RemoteError: hydrateCrdtFromProto requires an empty collaborative document.\n\u001b[31mERROR: Could not find a version that satisfies the requirement duckdb (from versions: none)\u001b[0m\u001b[31m\n\u001b[0m\u001b[31mERROR: No matching distribution found for duckdb\u001b[0m\u001b[31m\n\u001b[0m"
  },
  "yfinance": {
    "returncode": 1,
    "tail": "raceback (most recent call last):\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/patches/warm_spreadsheet_runtime_on_startup.py\", line 26, in warm_spreadsheet_runtime_on_startup\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 785, in warm_spreadsheet_runtime\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 720, in _warm_feature_flows\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/spreadsheet_warmup.py\", line 704, in _warm_collaboration_flows\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/generated/interface/models.py\", line 32317, in hydrate_crdt_from_proto\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/remote.py\", line 749, in __call__\n  File \"/tmp/tmp.L2TH2Y5coc/artifact_tool_v2-2.8.22/artifact_tool/rpc/client.py\", line 150, in call\nartifact_tool.rpc.client.RemoteError: hydrateCrdtFromProto requires an empty collaborative document.\n\u001b[31mERROR: Could not find a version that satisfies the requirement yfinance (from versions: none)\u001b[0m\u001b[31m\n\u001b[0m\u001b[31mERROR: No matching distribution found for yfinance\u001b[0m\u001b[31m\n\u001b[0m"
  }
}

Installation was attempted into a project-local directory only. No global
Python environment was modified.

## Focused closure tests

Exit code: 4

## Interpretation

The unavailable packages are a limitation of this execution environment when
installation cannot complete; they do not prove that the packages are absent
from the user's AWS/development environment.

If installation is blocked, the user should run the project's normal dependency
installation in its development/CI environment and then run the complete
pytest suite.

AWS/E2E verification remains a separate final production gate.

NOT deployed to AWS.
NOT production-certified.
