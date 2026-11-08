# Physics change test: 50 steps × 3 consecutive episodes

Train normally in **training mode**. After **3 consecutive episodes with at least 50 steps each**, prompt the experimenter before the next episode to choose: reduce force to **5 N**, increase cart mass to **2 kg**, or keep the original physics. An episode below 50 steps resets the consecutive-success count. The prompt appears only once per run, including when the experimenter chooses to keep the original physics.

These insertion instructions apply to the corrected control-mode code. The changes preserve the existing neural network and its learned weights.

## 1. Choose the file

| Path | File | Function |
|---|---|---|
| Brian2 simulation | `Brian2-Path/brian_integration.py` | `Brian2CartPoleIntegration.train()` |
| Hardware | `Hardware-Pythonnet-Path/run_cartpole.py` | `run_integrated_dishbrain()` |

For an initial Brian2 test, edit only the file in the first row. Place the switching logic inside the training loop so it controls when the physics changes. Do not apply the new parameters immediately after `gym.make(...)`.

## 2. Initialize the counters before the episode loop

For Brian2, find `for episode in range(num_episodes):`.
For hardware, find `for episode in range(episodes):`.

Add these two lines **immediately above** the corresponding `for` loop. Use the same indentation as `for` (8 spaces in the current code). Keep them outside the loop so the counters persist across episodes.

```python
        consecutive_successes = 0
        decision_made = False
```

## 3. Add the decision logic after each episode

**Brian2:** Insert the following lines after the existing `Episode ... Reward ... Length ...` print statement and before `self.env.close()`, while still inside the `for episode` loop:

```python
            steps_this_episode = self.current_episode_length
            physics = self.env.unwrapped
```

**Hardware:** Insert the following lines after `episode_rewards.append(gym_api.total_reward)` and before the existing inter-episode waiting logic:

```python
            steps_this_episode = step_count
            physics = gym_api.env.unwrapped
```

Then add this shared block **immediately below** the two lines for your chosen path. Indent the outermost `if` by 12 spaces, matching those assignments:

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

Run each experiment from the default physics and enter `1`, `2`, or `3` at the prompt. Do not add other assignments that change force or mass before the trigger.

-----

# To Run on Windows
## 4. Run the experiment

From the repository root, run in Windows PowerShell:

```powershell
$env:PYTHONPATH = (Get-Location).Path
python Brian2-Path/brian_integration.py --control-mode training --episodes 100
```

For hardware, replace the script path in the command with `Hardware-Pythonnet-Path/run_cartpole.py`.

This snippet keeps the original total episode limit and does not automatically extend training after the switch. If the trigger never occurs, no prompt appears. The training loop pauses while waiting for input, although background hardware acquisition may continue. For controlled experiments, select the condition in advance and switch automatically at the trigger to standardize the waiting time.
