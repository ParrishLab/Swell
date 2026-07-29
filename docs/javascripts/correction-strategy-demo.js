(function () {
  "use strict";

  const TOOLS = {
    prompts: {
      label: "Point / box prompts",
      detail: "Use when SAM can express the correction from target and background cues.",
    },
    paint: {
      label: "Brush / eraser / fill",
      detail: "Use for exact local changes to the final mask on the current frame.",
    },
    groundTruth: {
      label: "Lock ground truth",
      detail: "Use after a nonempty mask is trustworthy and should be protected as a mask seed.",
    },
    region: {
      label: "Persistent region",
      detail: "Use for the same include or exclude constraint across an inclusive frame range.",
    },
    propagate: {
      label: "Run Propagation",
      detail: "Use when corrected anchor data should influence other frames in the selected range.",
    },
  };

  const SCENARIOS = [
    {
      id: "prompt-fit",
      tab: "Model nearly right",
      title: "The mask is close, but its semantic boundary is wrong",
      clue:
        "The target is recognizable and the error can be described as “include this tissue” or “avoid that structure.”",
      frames: ["settled", "settled", "target", "caution", "settled", "settled", "settled"],
      frameLabel: "Frame 3 is the current correction target; frame 4 needs review.",
      recommendation: "Refine the current frame with point or box prompts.",
      tools: ["prompts"],
      steps: [
        "Place positive prompts on missed target tissue and negative prompts on unwanted tissue, or tighten the box.",
        "Inspect the regenerated current-frame mask before treating it as an anchor.",
        "Run Propagation only if this correction should influence neighboring frames.",
      ],
      caution:
        "Prompt refinement invokes the model. Use direct paint instead when you need a precise pixel-level correction that prompts cannot reliably express.",
    },
    {
      id: "local-defect",
      tab: "One-frame defect",
      title: "One frame has a small local defect, while its neighbors are sound",
      clue:
        "Ghost outlines remain consistent on both sides of the frame, and the leverage spike is isolated rather than the start of continuing drift.",
      frames: ["settled", "settled", "settled", "target", "settled", "settled", "settled"],
      frameLabel: "Only frame 4 needs a local final-mask correction.",
      recommendation: "Correct the final mask directly with brush, eraser, or fill.",
      tools: ["paint"],
      steps: [
        "Use Brush or Fill + to restore missing mask, or Eraser / Fill - to remove excess mask.",
        "Check the adjacent ghost outlines to confirm the defect is truly isolated.",
        "Leave propagation alone when the edit is only for this frame; rerun only when you want the paint anchor to affect other frames.",
      ],
      caution:
        "Paint layers are propagation anchors, but they do not change other frames until propagation is run again.",
    },
    {
      id: "downstream-drift",
      tab: "Continuing drift",
      title: "The mask begins drifting and stays wrong downstream",
      clue:
        "Future ghost outlines depart from the anatomy at the first red frame, and several later leverage cells remain elevated.",
      frames: ["settled", "settled", "target", "trouble", "trouble", "trouble", "trouble"],
      frameLabel: "Frame 3 is the earliest trustworthy correction point; drift continues afterward.",
      recommendation: "Correct the earliest credible divergence, then rerun propagation.",
      tools: ["prompts", "paint", "propagate"],
      steps: [
        "Use ghosts and leverage to find where the sequence first becomes anatomically wrong, not merely the reddest later frame.",
        "Choose prompts when the model can infer the desired boundary; choose paint for an exact correction.",
        "Run Propagation across the intended range so the new anchor can refine downstream masks.",
      ],
      caution:
        "The suggested-correction frame is a triage signal, not proof. Always confirm the anatomy before editing or propagating.",
    },
    {
      id: "repeated-zone",
      tab: "Repeated fixed area",
      title: "The same anatomical area must always be included or excluded",
      clue:
        "A stationary vessel, border artifact, or missed cortical patch recurs in the same location across a known frame interval.",
      frames: ["caution", "target", "target", "target", "target", "target", "settled"],
      frameLabel: "One persistent constraint applies across frames 2 through 6.",
      recommendation: "Draw a persistent Include or Exclude Region with the intended frame range.",
      tools: ["region"],
      steps: [
        "Draw the polygon around the fixed anatomical area and choose Include or Exclude.",
        "Set its one-based, inclusive start and end frames, then verify it on frames near both ends.",
        "Use the resulting final masks for review and export; no propagation rerun is required for the region itself.",
      ],
      caution:
        "Persistent regions modify final masks and exports but do not seed propagation. Exclude regions win where constraints overlap.",
    },
    {
      id: "trusted-seed",
      tab: "Trusted anchor",
      title: "A corrected mask is trusted and must remain a fixed propagation seed",
      clue:
        "The current frame has a nonempty, carefully reviewed mask that should be protected from model overwrite on later runs.",
      frames: ["settled", "settled", "target", "settled", "settled", "settled", "settled"],
      frameLabel: "Frame 3 is a reviewed mask seed for the next propagation run.",
      recommendation: "Lock the current frame as ground truth, then propagate when ready.",
      tools: ["groundTruth", "propagate"],
      steps: [
        "Finish and inspect the current mask; an empty frame cannot be locked as ground truth.",
        "Click “Lock current frame as ground truth” in the View section.",
        "Run Propagation when you want the protected mask seed to guide the selected range.",
      ],
      caution:
        "Ground-truth locking preserves a trusted mask seed; it is not a substitute for correcting an approximate mask first.",
    },
  ];

  let nextDemoId = 0;

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  class CorrectionStrategyDemo {
    constructor(root) {
      this.root = root;
      this.id = `swell-correction-strategy-${nextDemoId += 1}`;
      this.activeIndex = 0;
      this.tabs = [];
    }

    initialize() {
      this.root.replaceChildren();
      this.build();
      this.selectScenario(0, false);
    }

    build() {
      const shell = element("section", "swell-correction-strategy-demo__shell");
      shell.setAttribute("aria-label", "Correction strategy decision guide");

      const header = element("div", "swell-correction-strategy-demo__header");
      header.append(
        element("strong", "", "Choose from the pattern you observe"),
        element(
          "span",
          "",
          "Diagnostics locate suspicious frames; anatomy determines the correction."
        )
      );
      shell.append(header);

      const tabList = element("div", "swell-correction-strategy-demo__tabs");
      tabList.setAttribute("role", "tablist");
      tabList.setAttribute("aria-label", "Correction scenarios");
      SCENARIOS.forEach((scenario, index) => {
        const tab = element("button", "swell-correction-strategy-demo__tab", scenario.tab);
        tab.type = "button";
        tab.id = `${this.id}-tab-${scenario.id}`;
        tab.setAttribute("role", "tab");
        tab.setAttribute("aria-controls", `${this.id}-panel`);
        tab.addEventListener("click", () => this.selectScenario(index, true));
        tab.addEventListener("keydown", (event) => this.onTabKeydown(event, index));
        this.tabs.push(tab);
        tabList.append(tab);
      });
      shell.append(tabList);

      this.panel = element("div", "swell-correction-strategy-demo__panel");
      this.panel.id = `${this.id}-panel`;
      this.panel.setAttribute("role", "tabpanel");
      this.panel.tabIndex = 0;

      const observation = element("div", "swell-correction-strategy-demo__observation");
      const eyebrow = element("span", "swell-correction-strategy-demo__eyebrow", "Observed pattern");
      this.title = element("h3", "", "");
      this.clue = element("p", "", "");
      this.timeline = element("div", "swell-correction-strategy-demo__timeline");
      this.timeline.setAttribute("role", "img");
      this.frameLabel = element("p", "swell-correction-strategy-demo__frame-label", "");
      const legend = element("p", "swell-correction-strategy-demo__legend");
      legend.innerHTML =
        '<span class="is-settled"></span> settled '
        + '<span class="is-caution"></span> review '
        + '<span class="is-target"></span> correction target '
        + '<span class="is-trouble"></span> continuing trouble';
      observation.append(eyebrow, this.title, this.clue, this.timeline, this.frameLabel, legend);

      const guidance = element("div", "swell-correction-strategy-demo__guidance");
      guidance.append(element("span", "swell-correction-strategy-demo__eyebrow", "Recommended workflow"));
      this.recommendation = element("h3", "", "");
      this.steps = element("ol", "swell-correction-strategy-demo__steps");
      this.toolList = element("div", "swell-correction-strategy-demo__tools");
      this.caution = element("p", "swell-correction-strategy-demo__caution", "");
      guidance.append(this.recommendation, this.steps, this.toolList, this.caution);

      this.panel.append(observation, guidance);
      shell.append(this.panel);

      this.status = element("p", "swell-correction-strategy-demo__sr-status", "");
      this.status.setAttribute("aria-live", "polite");
      shell.append(this.status);
      this.root.append(shell);
    }

    onTabKeydown(event, index) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === "ArrowLeft") nextIndex = (index - 1 + SCENARIOS.length) % SCENARIOS.length;
      if (event.key === "ArrowRight") nextIndex = (index + 1) % SCENARIOS.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = SCENARIOS.length - 1;
      this.selectScenario(nextIndex, true);
      this.tabs[nextIndex].focus();
    }

    selectScenario(index, announce) {
      this.activeIndex = Math.max(0, Math.min(index, SCENARIOS.length - 1));
      const scenario = SCENARIOS[this.activeIndex];
      this.tabs.forEach((tab, tabIndex) => {
        const selected = tabIndex === this.activeIndex;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
      });
      this.panel.setAttribute("aria-labelledby", this.tabs[this.activeIndex].id);
      this.title.textContent = scenario.title;
      this.clue.textContent = scenario.clue;
      this.frameLabel.textContent = scenario.frameLabel;
      this.timeline.setAttribute(
        "aria-label",
        `Seven-frame diagnostic timeline. ${scenario.frameLabel}`
      );
      this.timeline.replaceChildren();
      scenario.frames.forEach((state, frameIndex) => {
        const cell = element(
          "span",
          `swell-correction-strategy-demo__frame is-${state}`,
          String(frameIndex + 1)
        );
        cell.title = `Frame ${frameIndex + 1}: ${state}`;
        this.timeline.append(cell);
      });
      this.recommendation.textContent = scenario.recommendation;
      this.steps.replaceChildren();
      scenario.steps.forEach((step) => this.steps.append(element("li", "", step)));
      this.toolList.replaceChildren();
      Object.entries(TOOLS).forEach(([toolId, tool]) => {
        const active = scenario.tools.includes(toolId);
        const card = element(
          "div",
          `swell-correction-strategy-demo__tool${active ? " is-recommended" : ""}`
        );
        const heading = element("strong", "", tool.label);
        const state = element("span", "", active ? "Use here" : "Different pattern");
        const detail = element("small", "", tool.detail);
        card.append(heading, state, detail);
        this.toolList.append(card);
      });
      this.caution.textContent = scenario.caution;
      if (announce) {
        this.status.textContent = `${scenario.tab}. ${scenario.recommendation}`;
      }
    }
  }

  function mountCorrectionStrategyDemos() {
    document.querySelectorAll("[data-swell-correction-strategy-demo]").forEach((root) => {
      if (root.dataset.swellCorrectionStrategyMounted === "true") return;
      root.dataset.swellCorrectionStrategyMounted = "true";
      try {
        const demo = new CorrectionStrategyDemo(root);
        root.swellCorrectionStrategyDemo = demo;
        demo.initialize();
      } catch (error) {
        root.replaceChildren(
          element(
            "p",
            "swell-correction-strategy-demo__fallback",
            `Correction strategy guide unavailable: ${error.message}`
          )
        );
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountCorrectionStrategyDemos, { once: true });
  } else {
    mountCorrectionStrategyDemos();
  }
  if (typeof document$ !== "undefined") document$.subscribe(mountCorrectionStrategyDemos);
}());
