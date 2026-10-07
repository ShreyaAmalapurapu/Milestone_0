## Quick run, step by step

Run these in order from a terminal. Each step is explained in more detail in the sections below.

1. **Go to your clone of the repo:**

   ```bash
   cd swe-marathon-course-milestone-0
   ```

2. **Put your key in `dev.env`** (replace `<your-key>` with the key that was shared with you):

   ```bash
   sed -i '' 's|^OPENAI_API_KEY=.*|OPENAI_API_KEY="<your-key>"|' dev.env
   ```

   On Linux, drop the `''` after `-i`. This is the default route (OpenAI). If you were given an
   OpenRouter key or Bedrock credentials, fill in `OPENROUTER_API_KEY` or the AWS keys in `dev.env` instead
   (see [below](#the-scripts-youll-use-run_student_bedrocksh-or-run_student_openroutersh)).

3. **Check Docker works** (Docker Desktop must be running):

   ```bash
   docker run hello-world
   ```

   If Docker isn't installed or this fails, see [below](#1-docker-usable-without-sudo).

4. **Check `uv` is installed:**

   ```bash
   uv --version
   ```

   If `uv` isn't installed, see [below](#2-uv).

5. **Go to the student scripts folder:**

   ```bash
   cd tasks/slack-clone-course/student-files
   ```

6. **Run milestone 0:**

   ```bash
   ./run_student_openai.sh 0   # or ./run_student_openrouter.sh 0 for OpenRouter, ./run_student_bedrock.sh 0 for Bedrock
   ```

7. **If you see `student-files/spec does not point at milestone 0`**, create the spec link and run
   step 6 again:

   ```bash
   ln -sfn ../course-staff-files/final_task/environment/milestone-specs/milestone-0-specs spec
   ./run_student_openai.sh 0   # or the script you used in step 6
   ```

8. **Wait for it to finish** (anywhere from 3 to 10 minutes). A successful run ends with a results
   table and a cost line:

   ```text
   ┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
   ┃ Trials ┃ Exceptions ┃  Mean ┃
   ┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
   │      0 │          0 │ 0.000 │
   └────────┴────────────┴───────┘
   Results written to .../tasks/slack-clone-course/jobs/<timestamp>/result.json
   COST: total=$<amount>
   ```

   `Trials 0` and `Mean 0.000` are expected. See [how to read the result](#3-what-to-expect--how-to-read-the-result).

9. **Look at the results.** They are saved in `tasks/slack-clone-course/jobs/<timestamp>/`. See
   [where to look after a run](#3-what-to-expect--how-to-read-the-result) for what each file means.

## Prerequisites

Install these once, before anything else.

### 1. Docker (usable without `sudo`)

1. Install Docker by following the [official guide](https://docs.docker.com/get-docker/) for your
   OS. On macOS or Windows, that means Docker Desktop, and it must be running whenever you run an
   experiment.
2. **Linux only:** add yourself to the `docker` group so Docker works without `sudo`. Without
   this, Harbor's `docker compose` calls fail.

   ```bash
   sudo usermod -aG docker $USER
   # then log out and log back in (or reboot) for the group change to take effect
   ```

3. Check that it works without `sudo`:

   ```bash
   docker run hello-world
   ```

### 2. `uv`

Install [`uv`](https://docs.astral.sh/uv/), the Python package manager the scripts use to set up
Harbor:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version   # check it's on your PATH (open a new terminal if not)
```

## Student quickstart: running a milestone (slack-clone-course)

In this assignment, we will be implementing the **slack-clone** problem from SWE-Marathon. We have
broken the project into smaller milestones, and this is **milestone 0**.

Milestone 0 has two goals:

1. Make sure every student has the infrastructure up and running on their laptop.
2. Help students get familiar with the structure of the codebase.

### The scripts you'll use: `run_student_bedrock.sh`, `run_student_openrouter.sh`, `run_student_openai.sh`

There are three scripts in [`tasks/slack-clone-course/student-files/`](tasks/slack-clone-course/student-files/).
They do the same thing and differ only in how they reach the LLM. The default is
`run_student_openai.sh`. **Pick the one that matches the credentials you received from the TAs**
and use it for all your experiments:

| If you were given... | Use this script |
| --- | --- |
| An OpenAI API key (default) | [`run_student_openai.sh`](tasks/slack-clone-course/student-files/run_student_openai.sh) |
| An OpenRouter API key | [`run_student_openrouter.sh`](tasks/slack-clone-course/student-files/run_student_openrouter.sh) |
| AWS Bedrock credentials | [`run_student_bedrock.sh`](tasks/slack-clone-course/student-files/run_student_bedrock.sh) |

Below, `run_student_<platform>.sh` means whichever of the three you picked. Each call launches one trial that performs the following steps:

| Step | What happens |
| --- | --- |
| Environment | Builds the task's Docker environment. |
| Agent | Fixes the agent to `mini-swe-agent` **[Do Not Change]** |
| LLM | Fixes the LLM to `GPT 5.6 Luna`, served by OpenAI (default), OpenRouter, or AWS Bedrock depending on the script **[Do Not Change]** |
| Input | Points the agent to the current milestone's spec (or whatever `student-files/spec` points at). |
| Time budget | Sets the time budget to 50 minutes |
| Output | Saves under `tasks/slack-clone-course/jobs/<timestamp>/`, the agent's transcript and the code it wrote, then prints the run's total LLM cost. |

**Invocation:**

```bash
cd tasks/slack-clone-course/student-files
./run_student_openai.sh <milestone> [extra harbor args]       # OpenAI (default)
./run_student_openrouter.sh <milestone> [extra harbor args]   # OpenRouter
./run_student_bedrock.sh <milestone> [extra harbor args]      # AWS Bedrock
```

| Argument | Required | Meaning |
| --- | --- | --- |
| `<milestone>` | yes | The milestone number, e.g. `0`. It must match the milestone that `student-files/spec` points at (see step 1 below), or the script exits before starting anything. |
| `[extra harbor args]` | no | Anything after the milestone is passed straight to `harbor run`. You won't need these for milestone 0. |

**What the script expects to already be in place:**

- **`dev.env` at the repo root** with the keys for the route you use filled in (you have received this information from the TAs). The script sources this file automatically. There are three routes to the same model, GPT 5.6 Luna:
  - **OpenAI** (`run_student_openai.sh`, default): `OPENAI_API_KEY`
  - **OpenRouter** (`run_student_openrouter.sh`): `OPENROUTER_API_KEY`
  - **Bedrock** (`run_student_bedrock.sh`): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `BEDROCK_ARN_GPT_5_6_LUNA`
- **The `student-files/spec` symlink** pointing at `milestone-<N>-specs` for the milestone you pass (step 1).
- **Docker** installed and running, plus [`uv`](https://docs.astral.sh/uv/). The script uses `uv` to create a local `.venv` with Harbor on the first run.

### 1. Point `student-files/spec` at the milestone's specs

`run_student_<platform>.sh` refuses to start unless `student-files/spec` is a symlink to the right milestone:

```text
❯ ./run_student_openai.sh 0   # or ./run_student_openrouter.sh 0 / ./run_student_bedrock.sh 0
student-files/spec does not point at milestone 0.
  expected: ../course-staff-files/final_task/environment/milestone-specs/milestone-0-specs
  actual:   <missing or not a symlink>
WERE YOU MODIFYING THE CORRECT SPECS FILE?
```

Fix it with:

```bash
cd tasks/slack-clone-course/student-files
ln -sfn ../course-staff-files/final_task/environment/milestone-specs/milestone-0-specs spec
```

**What this does, and why the spec matters:**

- **The symlink:** `ln -sfn` makes `student-files/spec` a symbolic link to the milestone's spec folder
  (in this case `course-staff-files/final_task/environment/milestone-specs/milestone-0-specs/`). As this is a
  symbolic link, any change to `student-files/spec` will modify in place
  `course-staff-files/final_task/environment/milestone-specs/milestone-0-specs`.
- **How the spec reaches the agent:** when you run `run_student_<platform>.sh 0`, it first checks that this
  link points at milestone 0. It then points the task's `environment/spec` at the same folder, and
  the Docker build copies it into the container at `/spec`.
- **What the agent does with it:** the agent's task prompt
  (`course-staff-files/final_task/instruction.md`) tells it to read `/spec/README.md` before doing
  anything else and to follow it.
- **Spec vs. prompt:** `instruction.md` is a high-level, natural-language description of the
  intended slack-clone project. The `spec` is the milestone-specific guidance that focuses the agent on one slice of it and says how to
  meet that slice. For milestone 0, the spec lists four baseline conditions the agent must verify
  before it submits:
  1. `/api/health` works.
  2. All three nodes report their own `node_id`.
  3. A WebSocket connection with a bad token is rejected.
  4. The other nodes survive one node being killed.

  In this course, you will see that the better the spec, the more likely an LLM agent is to
  complete the task correctly.

### 2. Run the milestone

```bash
./run_student_openai.sh 0       # if you use OpenAI (default)
./run_student_openrouter.sh 0   # if you use OpenRouter
./run_student_bedrock.sh 0      # if you use AWS Bedrock
```

Expected output:

```text
spec -> milestone-specs/milestone-0-specs (left in place for the trial; not cleaned up after)
Using CPython 3.13.5 interpreter at: .../python3
Creating virtual environment at: .venv
      Built long-horizon @ file:///.../swe-marathon-course
Installed <N> packages in <T>ms
  1/1 Mean: 0.000 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ <H:MM:SS> 0:00:00

┏━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┓
┃ Trials ┃ Exceptions ┃  Mean ┃
┡━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━┩
│      0 │          0 │ 0.000 │
└────────┴────────────┴───────┘

Results written to tasks/slack-clone-course/jobs/<timestamp>/result.json
COST: total=$<amount>
```

### 3. What to expect / how to read the result

| What you see | What it means |
| --- | --- |
| Stuck on `starting environment...`, and `docker ps -a` shows no container | Normal. Harbor is still running `docker compose build`, and BuildKit build steps don't appear in `docker ps`. The first cold build can take up to 20 min (`build_timeout_sec = 1200`). Cached rebuilds take seconds. The container (`final_task__<id>__env-main-1`) shows up once the build finishes. |
| `Trials 0`, `Mean 0.000` | Ignore this. |
| `Exceptions 0` | The agent ran and exited cleanly. |
| `COST: total=$<amount>` | The total LLM cost of the run, read from `result.json`'s `cost_usd` and printed by the script after Harbor finishes. |

> **⚠️ A very short or very cheap run means the agent probably did not complete.** A real
> milestone-0 attempt does actual work across many steps — expect several minutes of
> runtime and a non-trivial cost. If a run finishes in roughly a minute or two and costs
> very little (around $0.20 or less), and the implementation in `artifacts/app/` is
> incomplete, the agent almost certainly exited prematurely. **Re-run it once.** If it keeps
> happening, the problem is likely a bug in your spec/instructions or your setup — not a
> fluke — so fix that before spending more runs.

Where to look after a run (`tasks/slack-clone-course/jobs/<timestamp>/<trial>/`):

- `agent/mini-swe-agent.txt`: the full agent transcript. A clean exit ends with `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` and `Saved trajectory to ...`.
- `artifacts/app/`: the code the agent produced (`app.py`, `start.sh`, `requirements.txt`, ...).
- `result.json`: timings, token counts, cost, and `exception_info` (`null` means no crash).
- `agent/format_errors.jsonl`: model responses with malformed actions. A few entries are fine, because the agent recovers.

---

<h1 align="center">SWE-Marathon</h1>

<p align="center"><em>Can agents autonomously complete ultra-long-horizon software work?</em></p>


## Links

- [Website](https://www.swe-marathon.org/)
- [Paper](https://arxiv.org/abs/2606.07682)
- [Leaderboard](https://www.swe-marathon.org/#leaderboard)
- [Tasks](https://www.swe-marathon.org/#tasks)


## News
- [09/2026] 🚀 Featured on the [Qwen3.8-Max model card](https://x.com/Alibaba_Qwen/status/2094968708288680276?s=20)!
- [08/2026] 🔶 Featured on the [Hy4 preview model card](https://hy.tencent.ai/research/hy4-preview)!
- [08/2026] ⭐ Featured on the [GLM 5.3 model card](https://z.ai/blog/glm-5.3)!
- [08/2026] ⚙️ Featured on the [Grok 4.6 model card](https://media.x.ai/v1/website/card-4p6-4cd2dc57.pdf)!
- [07/2026] ➕ SWE-Marathon [v1.1 released](https://x.com/rishi_desai2/status/2087216551653146706?s=20)!
- [07/2026] 🌙 Featured on the [Kimi K3 model card](https://www.kimi.com/blog/kimi-k3)!
- [07/2026] 🔥 Featured on the [Grok 4.5 model card](https://x.ai/news/grok-4-5)!
- [06/2026] 🚀 Featured on the [GLM 5.2 model card](https://z.ai/blog/glm-5.2)!
- [06/2026] ⚡ SWE-Marathon [v1.0 released](https://x.com/rishi_desai2/status/2062930906818769356?s=20)!


## Citation

```bibtex
@misc{swemarathon_2026,
  title        = {{SWE-Marathon: Can Agents Autonomously Complete Ultra-Long-Horizon Software Work?}},
  author       = {Rishi Desai and Jesse Hu and Joan Cabezas and Neel Harsola and Pratyush Shukla and Daniel Wang and Xiangyi Li and Roey Ben Chaim and Adnan El Assadi and Omkaar Mukund Kamath and Fenil Faldu and Prannay Hebbar and Jiankai Sun and Yiyuan Li and Pramod Srinivasan and Ishan Gupta and Christopher Settles and Derek Chen and Pranav Raja and Albert Liu and Marek Šuppa and Nevasini Sasikumar and Luyang Kong and Erik Quintanilla and Ivan Bercovich and Steven Dillmann},
  year         = {2026},
  howpublished = {\url{https://arxiv.org/abs/2606.07682}},
  note         = {arXiv:2606.07682}
}
```

## License

[Apache License 2.0](LICENSE)
