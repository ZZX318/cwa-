# plan_hash parity vs 463badb 「新增，不改已冻结主表」

基线：`git worktree add --detach /workspace/wt-463badb 463badb`，两棵树各自 live 运行 `generate_plan`（`scripts/plan_hash_parity_463badb.py`，cwd=各树根），w=2, U=2, wd=0, configs/job.ablation.crosswind.json，未传 repair_lanes/min_buffer（即默认关）。
修复：`planning/model.py` `public_config()` 在 repair_lanes/min_buffer 取默认 0 时不序列化；`config_fingerprint` 与 `plan["config"]` 都用它。旧 DEFAULT 键（wind_speed 等）hash 方式不变。

| scheme | seed | offset | 463badb plan_hash | HEAD plan_hash | plan_hash 相等 | segments_digest 相等 |
|---|---|---|---|---|---|---|
| S1 | 0 | 0.0 | `7712a29eff86166b1a1ef3f74cb617a9210ee967d77f9b4a6f837c327693da3b` | `7712a29eff86166b1a1ef3f74cb617a9210ee967d77f9b4a6f837c327693da3b` | True | True |
| S1 | 1 | 0.0 | `5af556d5527b6c74f0ac4d4db5f1d7a4f1d7279b4f82176c61c6b92309156b24` | `5af556d5527b6c74f0ac4d4db5f1d7a4f1d7279b4f82176c61c6b92309156b24` | True | True |
| S1 | 2 | 0.0 | `1010c6b95a166da4f0b16d928d55aaa0dc40bc8735532a3bccdab98d50eca1b5` | `1010c6b95a166da4f0b16d928d55aaa0dc40bc8735532a3bccdab98d50eca1b5` | True | True |
| S1 | 3 | 0.0 | `f7a496d05cc001f0e2da44e3480452f6142b6880b94649e82abc65e4d667da6e` | `f7a496d05cc001f0e2da44e3480452f6142b6880b94649e82abc65e4d667da6e` | True | True |
| S1 | 4 | 0.0 | `b14dd503ac87ba134a65296056244e4662097a276487468daa743afcae3171bd` | `b14dd503ac87ba134a65296056244e4662097a276487468daa743afcae3171bd` | True | True |
| S_h | 0 | 1.88 | `563734d2bcda050881af559c5e90402a225f92eb737a3e7c3e8c4d01819405fa` | `563734d2bcda050881af559c5e90402a225f92eb737a3e7c3e8c4d01819405fa` | True | True |
| S_h | 1 | 1.857 | `2a65e3af3aa4676836cae0a66683dc2c4aea8e70338f4817e240ac6b36f10231` | `2a65e3af3aa4676836cae0a66683dc2c4aea8e70338f4817e240ac6b36f10231` | True | True |
| S_h | 2 | 0.15 | `28e5386810932b657627258819dace2089b6e4d1e0eb4398ebaa33e0ee233709` | `28e5386810932b657627258819dace2089b6e4d1e0eb4398ebaa33e0ee233709` | True | True |
| S_h | 3 | 0.01 | `06f1b517cd93c2043d11c82d2176c97c4b28852f9730902459d0921930d59541` | `06f1b517cd93c2043d11c82d2176c97c4b28852f9730902459d0921930d59541` | True | True |
| S_h | 4 | 1.902 | `7a533e2701a7fcc7c48454ce020c76f6bfb5bc527d8ac8f389a23a4a9c38876f` | `7a533e2701a7fcc7c48454ce020c76f6bfb5bc527d8ac8f389a23a4a9c38876f` | True | True |

结论：10/10 plan_hash 与 segments_digest 逐一相等。
