# Physics change test: 50 steps × 3 consecutive episodes

在 **training mode** 下正常训练。连续 **3 局都达到至少 50 步** 后，在下一局开始前提示实验者选择：推力降到 **5 N**、小车质量增至 **2 kg**，或保持原参数。任一局不足 50 步，连续成功次数归零。每次运行只提示一次，选“保持原参数”后也不再提示。

以下是插入说明，适用于修正版控制代码。它不会重建神经网络或重置已有权重。

## 1. 选择要修改的文件

| 路径 | 文件 | 所在函数 |
|---|---|---|
| Brian2 模拟 | `Brian2-Path/brian_integration.py` | `Brian2CartPoleIntegration.train()` |
| 真实硬件 | `Hardware-Pythonnet-Path/run_cartpole.py` | `run_integrated_dishbrain()` |

如果先测试 Brian2，只改第一行对应的文件即可。这个任务控制“何时改变参数”，应放在训练循环里，不放在创建 `gym.make(...)` 的位置。

## 2. 在 episode 循环前初始化计数器

Brian2：找到 `for episode in range(num_episodes):`。
硬件：找到 `for episode in range(episodes):`。

在对应 `for` 的**正上方**添加以下两行，缩进与 `for` 一样（当前版本为 8 个空格）。不要放进循环内，否则每局都会重新归零。

```python
        consecutive_successes = 0
        decision_made = False
```

## 3. 在每局结束后添加判断

**Brian2**：放在打印 `Episode ... Reward ... Length ...` 的那一行之后、`self.env.close()` 之前，但仍位于 `for episode` 循环内部。先添加：

```python
            steps_this_episode = self.current_episode_length
            physics = self.env.unwrapped
```

**硬件**：放在 `episode_rewards.append(gym_api.total_reward)` 之后、原有局间等待逻辑之前。先添加：

```python
            steps_this_episode = step_count
            physics = gym_api.env.unwrapped
```

然后，在你选择的那组两行代码**紧下方**，添加以下共同代码。最外层 `if` 的缩进为 12 个空格，与上面的赋值相同：

```python
            if not decision_made:
                if steps_this_episode >= 50:
                    consecutive_successes += 1
                else:
                    consecutive_successes = 0
                # Count consecutive qualifying episodes, not total successes.

                if consecutive_successes >= 3:
                    choice = input(
                        "1: Force = 5 N; 2: Cart mass = 2 kg; "
                        "3: Keep original physics: "
                    )

                    if choice == "1":
                        physics.force_mag = 5.0
                        # Change force only. Cart mass remains 1 kg.
                    elif choice == "2":
                        physics.masscart = 2.0
                        physics.total_mass = physics.masscart + physics.masspole
                        # Update the cached total mass. Force remains 10 N.

                    decision_made = True
                    print(f"Physics decision after episode {episode + 1}: {choice}")
                    # Apply the selected condition from the next episode onward.
```

两种方案分别从默认参数开始运行，选择时输入 `1`、`2` 或 `3`。不要提前添加其他修改质量或推力的赋值。

## 4. 运行

在项目根目录的 Windows PowerShell 中运行：

```powershell
$env:PYTHONPATH = (Get-Location).Path
python Brian2-Path/brian_integration.py --control-mode training --episodes 100
```

硬件实验将上述命令中的文件路径换为 `Hardware-Pythonnet-Path/run_cartpole.py`。

注意：此片段保留原有总局数上限，不会自动增加切换后的局数。如果条件始终未达到，就不会提示。人工输入期间训练循环会等待；真实硬件的后台采集仍可能继续。正式实验可提前选方案、达到条件后自动切换，以统一等待时间。
