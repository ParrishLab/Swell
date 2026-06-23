# Specialist Baseline Proposal

## Purpose

Define a practical plan to evaluate a task-specific segmentation model for spreading depolarization (SD) masks alongside the current SAM 2.1 workflow.

This proposal is not a request to replace SAM immediately. The first goal is to answer a narrower question:

- Can a specialist model trained directly on our SD masks outperform or materially assist the current prompt-driven SAM 2.1 workflow?

## Problem Statement

The current analysis stack uses SAM 2.1 as an interactive video segmentation and propagation engine. In runtime:

- input frames are preprocessed into a visualization stack via smoothing, baseline subtraction, and global normalization
- SAM 2.1 is initialized as a video predictor
- user points or masks are injected on selected frames
- masks are propagated across the event window

Relevant implementation points:

- preprocessing stack generation: [swell/shared/frame_source/preprocessing.py](/Users/claydunford/Development/Combined tool test/swell/shared/frame_source/preprocessing.py)
- SAM 2.1 video predictor initialization: [swell/analysis/core/segmentation.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/segmentation.py)
- prompt-driven frame inference and propagation: [swell/analysis/core/inference_manager.py](/Users/claydunford/Development/Combined tool test/swell/analysis/core/inference_manager.py)

This architecture is strong for interactive editing, but it may not be the most data-efficient way to learn a narrow scientific segmentation task with a relatively small labeled dataset.

## Proposal

Train a specialist baseline model on the same SD data and preprocessing used by the current analysis workflow, then compare it directly against the current SAM 2.1 behavior.

Recommended model progression:

1. 2D baseline:
   - `nnU-Net` 2D or a small 2D U-Net
   - fastest path to a credible benchmark
2. 2.5D baseline:
   - center frame plus neighboring frames as channels, for example `t-1, t, t+1`
   - likely the best quality-to-compute tradeoff
3. Small 3D baseline:
   - only if temporal context appears critical and 2D/2.5D plateaus

The baseline should use the same preprocessed visualization frames that the app feeds to SAM 2.1. Training on raw TIFF intensities while evaluating against a runtime built on normalized visualization frames would optimize the wrong problem.

## Non-Goals

- Full replacement of the current SAM editing workflow in the first phase
- Immediate integration into the main analysis UI before offline evaluation
- Foundation-model retraining or larger-model selection as the primary lever

## Why This Is Worth Testing

Compared with SAM 2.1 fine-tuning, a specialist baseline has these advantages:

- lower compute cost
- simpler training loop
- more direct use of dense mask supervision
- easier experimentation on local hardware
- easier failure analysis

The main downside is reduced interactivity. A specialist model does not naturally replace prompt-based correction and propagation. That is why the first integration target should be an assistive path rather than a hard swap.

## Data Assumptions

Current labeled data shape:

- approximately 30 SD clips
- each clip already has:
  - raw TIFF frame folder
  - aligned ground-truth mask folder
- clips include additional pre-event and post-event context frames

These clips should be converted into a canonical training dataset with:

- train split
- validation split
- held-out test split

Split rules:

- split by clip or subject, not by frame
- keep all windows from a source clip in exactly one split
- preserve pre-event and post-event frames because they provide hard negatives

## Candidate Architectures

### Option A: 2D nnU-Net or 2D U-Net

Inputs:

- single preprocessed frame

Outputs:

- binary SD mask

Benefits:

- lowest compute cost
- easiest baseline to train and debug
- likely feasible on local RTX A2000 hardware

Risks:

- no explicit temporal context
- may flicker between adjacent frames

### Option B: 2.5D U-Net

Inputs:

- small temporal neighborhood as channels, for example `t-1, t, t+1`

Outputs:

- center-frame binary SD mask

Benefits:

- modest temporal awareness
- still lightweight compared with SAM 2.1
- likely the best first serious candidate

Risks:

- still not true propagation or memory-based tracking

### Option C: Small 3D U-Net

Inputs:

- short clip tensor

Outputs:

- mask volume or center-frame prediction

Benefits:

- strongest temporal modeling of the specialist options

Risks:

- noticeably higher VRAM cost
- slower training and tuning
- likely beyond the most comfortable range of the local RTX A2000

## Proposed Training Plan

### Phase 1: Data Preparation

Tasks:

- export the same preprocessed frames used by analysis runtime
- verify mask alignment against exported frames
- create train, validation, and test splits
- include metadata per clip:
  - source identifier
  - frame count
  - event bounds
  - optional quality flags

Acceptance criteria:

- every exported frame has a matching mask or explicit empty-mask entry
- no split leakage
- preprocessing parity with runtime confirmed on a sample set

### Phase 2: Baseline Training

Train a 2D or 2.5D specialist model first.

Recommended first pass:

- architecture: 2.5D U-Net or `nnU-Net` 2D
- objective:
  - Dice plus BCE or focal loss
- data sampling:
  - balance positive SD frames and hard negatives
  - oversample onset and weak-signal windows

Expected outputs:

- best checkpoint
- validation curves
- held-out predictions for test clips

### Phase 3: Comparative Evaluation

Run the trained model on the held-out set and compare to the current SAM 2.1 workflow under a fixed evaluation protocol.

### Phase 4: Integration Prototype

If the specialist baseline is promising, integrate it as an optional auto-initialization path before any deeper replacement work.

## Training Time and Compute Expectations

These are planning estimates, not guarantees.

### Local RTX A2000 + 64 GB RAM

Appropriate for:

- dataset export and validation
- small-scope experiments
- 2D or 2.5D baseline training
- overfit-on-a-few-clips smoke tests

Expected feasibility:

- 2D U-Net or 2D `nnU-Net`: feasible
- 2.5D U-Net: likely feasible with conservative batch sizes
- 3D U-Net: possible only with small clips or reduced resolution, and likely slow
- SAM 2.1 fine-tuning: not the preferred target for this machine

Time expectations:

- data conversion and verification: hours, not days
- first 2D/2.5D baseline run: several hours to roughly a day, depending on preprocessing size and training schedule
- iteration loop after the first run: fast enough for local model development

### HPC or Larger GPU Box

Appropriate for:

- repeated ablation runs
- 3D baseline experiments
- larger hyperparameter sweeps
- SAM 2.1 fine-tuning if still desired later

Time expectations:

- a single specialist-model run should usually be much cheaper than a SAM 2.1 fine-tune
- if the local baseline already performs well, HPC may only be needed for confirmation runs

## Integration Options

### Option 1: Offline Benchmark Only

Do not integrate into the app yet.

Use the specialist model only to answer:

- does a specialist model beat the current SAM workflow on held-out SD clips?

Benefits:

- lowest engineering risk
- cleanest scientific comparison

### Option 2: Auto-Initialization for Existing Workflow

Recommended first integration path.

Flow:

1. run specialist model on the current frame or selected event range
2. convert the probability map to a binary mask
3. inject that mask into the existing segmentation state
4. hand off to the current SAM-driven editing and propagation workflow

This aligns with the current runtime because propagation already supports mask injection via `add_new_mask(...)` and stores masks in `masks_cache`.

Benefits:

- preserves current UI and user mental model
- allows SAM to remain the interactive editor
- reduces dependence on manual point prompting

Risks:

- bad initial masks could anchor propagation incorrectly
- thresholding/calibration will need tuning

### Option 3: Full Automatic Segmentation Mode

Use the specialist model as a standalone segmentation backend.

Benefits:

- simplest inference behavior
- no prompt requirement

Risks:

- largest UI and workflow change
- loses the current strength of interactive correction unless we rebuild that path

## Recommended Integration Plan

Implement in this order:

1. offline benchmark
2. optional auto-initialization path
3. full backend replacement only if clearly justified

This treats the cause rather than the symptom. The immediate question is not "how do we put in a new model?" but "what model structure best solves the SD segmentation problem under our data and workflow constraints?"

## Measurement Plan

The specialist model must be compared against the current SAM 2.1 workflow, not against an abstract ideal.

### Baseline for Comparison

Current runtime baseline:

- same held-out clips
- same preprocessing path
- same event windows
- same prompt policy for SAM evaluation

Two SAM comparison modes should be measured:

1. Minimal-interaction SAM:
   - fixed prompt budget, for example one positive point on anchor frame
2. Practical-interaction SAM:
   - a realistic operator prompt/edit budget

If we compare a fully automatic specialist model against a heavily hand-corrected SAM session, the result will not be interpretable.

### Core Metrics

Frame-level segmentation:

- Dice
- IoU
- precision
- recall

Event-level behavior:

- onset-frame detection quality
- false positive frames per clip
- false negative frames per clip
- temporal stability between adjacent predictions

User-workflow metrics:

- prompts required per event
- manual correction time per event
- percent of events needing manual rescue

Operational metrics:

- inference time per clip
- GPU memory at inference
- failure modes by clip category

### Success Thresholds

The specialist baseline is worth deeper integration if it achieves one or more of the following on held-out data:

- better Dice/IoU than current SAM minimal-interaction mode
- materially fewer false positives on hard negatives
- substantially lower operator effort at equal or better quality
- stable initialization masks that make SAM propagation more reliable

## Evaluation Protocol

1. Freeze a held-out test set before training begins.
2. Train the specialist model only on train and validation data.
3. Run current SAM workflow on the same test set using a written prompt protocol.
4. Run specialist baseline on the same test set.
5. Compare quantitative metrics and review failure cases side by side.

Failure review categories should include:

- weak-signal SD
- noisy background
- vascular/confounding artifacts
- boundary ambiguity
- partial masks
- pre-event and post-event frames

## Engineering Work Items

### Data and Training

- build preprocessing export tool for specialist dataset generation
- define split manifest format
- add training scripts or a separate training workspace
- save per-run metadata and evaluation outputs

### Evaluation

- define held-out benchmark set
- implement metric computation scripts
- generate side-by-side qualitative review artifacts

### Integration Prototype

- add optional specialist-model checkpoint selection
- add inference wrapper for specialist model
- map predictions into `masks_cache`
- expose "Generate Initial Mask" as an optional action before propagation

## Risks

- dataset size may still be too small for robust generalization
- temporal behavior may require more than a 2D model can provide
- preprocessing parity mistakes could invalidate results
- operator-driven SAM comparison could be biased if prompt protocol is not standardized

## Decision Gates

### Gate 1: Training Feasibility

Can a 2D or 2.5D specialist baseline be trained reproducibly on local or accessible compute?

### Gate 2: Benchmark Quality

Does the specialist baseline beat or materially assist the current SAM workflow on held-out clips?

### Gate 3: Integration Value

Does optional auto-initialization improve operator speed or quality enough to justify product integration?

## Recommendation

Proceed with a specialist baseline project using this order:

1. export runtime-matched preprocessed training data
2. train a 2D or 2.5D baseline
3. benchmark against the current SAM workflow under a fixed protocol
4. if promising, integrate as an optional auto-initializer rather than a direct replacement

This is the lowest-risk way to find out whether the current bottleneck is model family mismatch rather than model size.
