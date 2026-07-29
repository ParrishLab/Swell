(function () {
  "use strict";

  const FRAME_COUNT = 120;
  const DEFAULT_FRAME = 38;
  const DEFAULT_BASELINE = 30;
  let nextDemoId = 0;

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function createElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function appendLabeledControl(container, labelText, control) {
    const label = createElement("label", "swell-event-range-demo__field");
    label.append(document.createTextNode(labelText));
    label.htmlFor = control.id;
    label.append(control);
    container.append(label);
  }

  class EventRangeDemo {
    constructor(root) {
      this.root = root;
      this.id = `swell-event-range-demo-${nextDemoId += 1}`;
      this.currentFrame = DEFAULT_FRAME;
      this.start = DEFAULT_FRAME;
      this.end = DEFAULT_FRAME;
      this.baselineCount = DEFAULT_BASELINE;
      this.savedEvent = null;
    }

    initialize() {
      this.root.replaceChildren();
      this.root.classList.add("swell-event-range-demo");
      this.build();
      this.render();
      this.announce("Event range demo ready. Use the frame slider or arrow keys to choose event bounds.");
    }

    build() {
      const shell = createElement("section", "swell-event-range-demo__shell");
      shell.setAttribute("aria-label", "Simulated event range marking dialog");

      const heading = createElement("div", "swell-event-range-demo__heading");
      heading.append(createElement("strong", "", "Mark Event — simulation"));
      heading.append(createElement("span", "", "Frames are a fixed illustrative recording; no event is saved to Swell."));
      shell.append(heading);

      const preview = createElement("div", "swell-event-range-demo__preview");
      preview.setAttribute("aria-hidden", "true");
      this.previewWave = createElement("div", "swell-event-range-demo__wave");
      this.previewWave.append(createElement("div", "swell-event-range-demo__wavefront"));
      preview.append(this.previewWave);
      this.previewCaption = createElement("div", "swell-event-range-demo__preview-caption");
      preview.append(this.previewCaption);
      shell.append(preview);

      const frameRow = createElement("div", "swell-event-range-demo__frame-row");
      this.frameReadout = createElement("output", "swell-event-range-demo__frame-readout");
      this.frameReadout.htmlFor = `${this.id}-frame`;
      frameRow.append(this.frameReadout);
      this.slider = document.createElement("input");
      this.slider.className = "swell-event-range-demo__slider";
      this.slider.id = `${this.id}-frame`;
      this.slider.type = "range";
      this.slider.min = "1";
      this.slider.max = String(FRAME_COUNT);
      this.slider.step = "1";
      this.slider.setAttribute("aria-label", "Preview frame");
      this.slider.addEventListener("input", () => this.setCurrentFrame(Number(this.slider.value)));
      frameRow.append(this.slider);
      shell.append(frameRow);

      const navigation = createElement("div", "swell-event-range-demo__navigation");
      navigation.setAttribute("aria-label", "Frame navigation");
      navigation.append(this.createButton("Prev", () => this.setCurrentFrame(this.currentFrame - 1)));
      navigation.append(this.createButton("Next", () => this.setCurrentFrame(this.currentFrame + 1)));
      navigation.append(this.createButton("Set Start", () => this.setStartFromCurrent()));
      navigation.append(this.createButton("Set End", () => this.setEndFromCurrent()));
      shell.append(navigation);

      const controls = createElement("div", "swell-event-range-demo__controls");
      const bounds = createElement("div", "swell-event-range-demo__bounds");
      this.startInput = this.createNumberInput("start", "Start frame", 1, FRAME_COUNT);
      this.endInput = this.createNumberInput("end", "End frame", 1, FRAME_COUNT);
      appendLabeledControl(bounds, "Start", this.startInput);
      appendLabeledControl(bounds, "End", this.endInput);
      controls.append(bounds);

      const baseline = createElement("div", "swell-event-range-demo__baseline");
      this.baselineInput = this.createNumberInput("baseline", "Baseline count", 1, FRAME_COUNT);
      appendLabeledControl(baseline, "Baseline count", this.baselineInput);
      this.baselineEnd = createElement("output", "swell-event-range-demo__derived");
      this.baselineEnd.id = `${this.id}-baseline-end`;
      const baselineEndLabel = createElement("span", "swell-event-range-demo__derived-label", "Baseline end (derived)");
      baselineEndLabel.append(this.baselineEnd);
      baseline.append(baselineEndLabel);
      controls.append(baseline);

      const contrast = createElement("div", "swell-event-range-demo__contrast");
      const contrastLabel = createElement("label", "", "Contrast");
      contrastLabel.htmlFor = `${this.id}-contrast`;
      this.contrastInput = document.createElement("input");
      this.contrastInput.id = `${this.id}-contrast`;
      this.contrastInput.type = "range";
      this.contrastInput.min = "0.5";
      this.contrastInput.max = "3";
      this.contrastInput.step = "0.05";
      this.contrastInput.value = "1";
      this.contrastOutput = createElement("output", "");
      this.contrastOutput.htmlFor = this.contrastInput.id;
      this.contrastInput.addEventListener("input", () => this.render());
      contrast.append(contrastLabel, this.contrastInput, this.contrastOutput);
      controls.append(contrast);
      shell.append(controls);

      const timeline = createElement("div", "swell-event-range-demo__timeline");
      timeline.setAttribute("aria-label", "Event range timeline");
      this.baselineBand = createElement("div", "swell-event-range-demo__band swell-event-range-demo__band--baseline");
      this.eventBand = createElement("div", "swell-event-range-demo__band swell-event-range-demo__band--event");
      this.playhead = createElement("div", "swell-event-range-demo__playhead");
      timeline.append(this.baselineBand, this.eventBand, this.playhead);
      shell.append(timeline);
      shell.append(createElement("p", "swell-event-range-demo__timeline-label", "Baseline (blue) · event range (green) · current preview frame (white)"));

      const footer = createElement("div", "swell-event-range-demo__footer");
      this.confirmButton = this.createButton("Confirm", () => this.confirm(), "swell-event-range-demo__button--primary");
      this.resetButton = this.createButton("Reset", () => this.reset());
      footer.append(this.resetButton, this.confirmButton);
      shell.append(footer);

      this.summary = createElement("p", "swell-event-range-demo__summary");
      shell.append(this.summary);
      this.status = createElement("p", "swell-event-range-demo__sr-status");
      this.status.setAttribute("aria-live", "polite");
      this.status.setAttribute("aria-atomic", "true");
      shell.append(this.status);
      this.root.append(shell);
    }

    createButton(label, action, extraClass) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `swell-event-range-demo__button${extraClass ? ` ${extraClass}` : ""}`;
      button.textContent = label;
      button.addEventListener("click", action);
      return button;
    }

    createNumberInput(name, label, min, max) {
      const input = document.createElement("input");
      input.id = `${this.id}-${name}`;
      input.type = "number";
      input.min = String(min);
      input.max = String(max);
      input.step = "1";
      input.inputMode = "numeric";
      input.setAttribute("aria-label", label);
      input.addEventListener("input", () => this.readInputs());
      input.addEventListener("change", () => this.normalizeInputs());
      return input;
    }

    readNumber(input, fallback) {
      const value = Number(input.value);
      return Number.isInteger(value) ? value : fallback;
    }

    readInputs() {
      this.start = this.readNumber(this.startInput, this.start);
      this.end = this.readNumber(this.endInput, this.end);
      this.baselineCount = this.readNumber(this.baselineInput, this.baselineCount);
      // Preserve a partially typed value; normalize it only when the field loses focus
      // or the simulated dialog is confirmed.
      this.render(false);
    }

    normalizeInputs() {
      this.start = clamp(this.readNumber(this.startInput, this.currentFrame), 1, FRAME_COUNT);
      this.end = clamp(this.readNumber(this.endInput, this.currentFrame), 1, FRAME_COUNT);
      this.baselineCount = clamp(this.readNumber(this.baselineInput, DEFAULT_BASELINE), 1, FRAME_COUNT);
      this.render();
    }

    setCurrentFrame(frame) {
      this.currentFrame = clamp(Math.round(frame), 1, FRAME_COUNT);
      this.render();
      this.announce(`Preview frame ${this.currentFrame} of ${FRAME_COUNT}.`);
    }

    setStartFromCurrent() {
      this.start = this.currentFrame;
      if (this.start > this.end) this.end = this.start;
      this.render();
      this.announce(`Start set to frame ${this.start}.`);
    }

    setEndFromCurrent() {
      this.end = this.currentFrame;
      if (this.end < this.start) this.start = this.end;
      this.render();
      this.announce(`End set to frame ${this.end}.`);
    }

    normalizedBounds() {
      const start = clamp(Math.round(this.start), 1, FRAME_COUNT);
      const end = clamp(Math.round(this.end), 1, FRAME_COUNT);
      return start <= end ? { start, end, swapped: false } : { start: end, end: start, swapped: true };
    }

    reset() {
      this.currentFrame = DEFAULT_FRAME;
      this.start = DEFAULT_FRAME;
      this.end = DEFAULT_FRAME;
      this.baselineCount = DEFAULT_BASELINE;
      this.savedEvent = null;
      this.contrastInput.value = "1";
      this.render();
      this.announce("Demo reset. Start and end both return to the current preview frame.");
    }

    confirm() {
      this.normalizeInputs();
      const bounds = this.normalizedBounds();
      this.start = bounds.start;
      this.end = bounds.end;
      this.savedEvent = { start: bounds.start, end: bounds.end, baselineCount: this.baselineCount };
      this.render();
      const swappedNote = bounds.swapped ? " Start and end were swapped to keep the range ordered." : "";
      this.announce(`Simulation confirmed: frames ${bounds.start} through ${bounds.end}.${swappedNote}`);
    }

    announce(message) {
      this.status.textContent = message;
    }

    render(syncInputs = true) {
      const bounds = this.normalizedBounds();
      const baselineEnd = Math.max(0, bounds.start - 1);
      const baselineStart = Math.max(1, baselineEnd - clamp(this.baselineCount, 1, FRAME_COUNT) + 1);
      const contrast = Number(this.contrastInput ? this.contrastInput.value : 1);
      const eventProgress = clamp((this.currentFrame - 25) / 60, 0, 1);

      this.slider.value = String(this.currentFrame);
      if (syncInputs) {
        this.startInput.value = String(this.start);
        this.endInput.value = String(this.end);
        this.baselineInput.value = String(this.baselineCount);
      }
      this.baselineEnd.textContent = baselineEnd ? `Frame ${baselineEnd}` : "No pre-event frame";
      this.frameReadout.textContent = `Frame ${this.currentFrame} / ${FRAME_COUNT}`;
      this.previewCaption.textContent = this.currentFrame < 25
        ? "Pre-event signal"
        : this.currentFrame > 85
          ? "Late event frame"
          : "Illustrative spreading-depression wave";
      this.previewWave.style.setProperty("--event-progress", String(eventProgress));
      this.previewWave.style.setProperty("--event-position", `${12 + eventProgress * 72}%`);
      this.previewWave.style.setProperty("--contrast", String(contrast));
      this.contrastOutput.textContent = `${contrast.toFixed(2)}×`;

      const width = 100 / FRAME_COUNT;
      const rangeWidth = (bounds.end - bounds.start + 1) * width;
      const baselineWidth = baselineEnd ? (baselineEnd - baselineStart + 1) * width : 0;
      this.eventBand.style.left = `${(bounds.start - 1) * width}%`;
      this.eventBand.style.width = `${rangeWidth}%`;
      this.baselineBand.style.left = `${(baselineStart - 1) * width}%`;
      this.baselineBand.style.width = `${baselineWidth}%`;
      this.playhead.style.left = `${(this.currentFrame - 0.5) * width}%`;

      const duration = bounds.end - bounds.start + 1;
      const durationUnit = duration === 1 ? "frame" : "frames";
      if (this.savedEvent) {
        const savedDuration = this.savedEvent.end - this.savedEvent.start + 1;
        const savedDurationUnit = savedDuration === 1 ? "frame" : "frames";
        const baselineUnit = this.savedEvent.baselineCount === 1 ? "frame" : "frames";
        this.summary.textContent = `Simulated event recorded: frames ${this.savedEvent.start}–${this.savedEvent.end} (${savedDuration} ${savedDurationUnit}), with ${this.savedEvent.baselineCount} baseline ${baselineUnit}.`;
      } else if (bounds.swapped) {
        this.summary.textContent = `Preview range: frames ${bounds.start}–${bounds.end} (${duration} ${durationUnit}). Confirm will swap inverted Start and End values, as the desktop app does.`;
      } else {
        this.summary.textContent = `Preview range: frames ${bounds.start}–${bounds.end} (${duration} ${durationUnit}). Baseline ends at frame ${baselineEnd || "none"}.`;
      }
    }
  }

  function mountEventRangeDemos() {
    document.querySelectorAll("[data-swell-event-range-demo]").forEach((root) => {
      if (root.dataset.swellEventRangeMounted === "true") return;
      root.dataset.swellEventRangeMounted = "true";
      try {
        const demo = new EventRangeDemo(root);
        root.swellEventRangeDemo = demo;
        demo.initialize();
      } catch (error) {
        root.replaceChildren(createElement("p", "swell-event-range-demo__fallback", `Event range demo unavailable: ${error.message}`));
      }
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountEventRangeDemos, { once: true });
  else mountEventRangeDemos();
  if (typeof document$ !== "undefined") document$.subscribe(mountEventRangeDemos);
}());
