(function () {
  "use strict";

  const WIDTH = 240;
  const HEIGHT = 156;
  const EVENT_START = 12; // zero-based; displayed as frame 13
  const EVENT_END = 20; // zero-based; displayed as frame 21
  const DEFAULT_BASELINE = 30;
  const DEFAULTS = {
    horizontalBarDenoise: false,
    smoothing: true,
    baselineSubtraction: true,
    globalNormalization: true,
    stabilization: false,
  };

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function createFrame(globalIndex) {
    const frame = new Float32Array(WIDTH * HEIGHT);
    const driftX = Math.sin(globalIndex * 0.58) * 3.4;
    const driftY = Math.cos(globalIndex * 0.43) * 2.3;
    const eventAge = globalIndex - EVENT_START;
    const eventStrength = eventAge >= 0 ? Math.exp(-Math.pow((eventAge - 3.0) / 3.1, 2)) : 0;

    for (let y = 0; y < HEIGHT; y += 1) {
      for (let x = 0; x < WIDTH; x += 1) {
        const sourceX = x - driftX;
        const sourceY = y - driftY;
        const corticalBand = Math.exp(-Math.pow((sourceY - (68 + Math.sin(sourceX / 31) * 5)) / 20, 2));
        const ventricle = Math.exp(
          -(
            Math.pow((sourceX - 122) / 27, 2)
            + Math.pow((sourceY - 92) / 13, 2)
          )
        );
        const eventWave = eventStrength * Math.exp(
          -(
            Math.pow((sourceX - (77 + eventAge * 11)) / 30, 2)
            + Math.pow((sourceY - 61) / 15, 2)
          )
        );
        const horizontalBand = (y % 18 < 5 ? 10 : -3) + Math.sin(y * 0.29) * 2.5;
        const deterministicNoise =
          Math.sin(x * 1.77 + y * 2.31 + globalIndex * 4.19) * 4.2
          + Math.sin(x * 0.43 - y * 1.13 + globalIndex) * 2.1;
        const slowIllumination = globalIndex * 0.8 + (x / WIDTH) * 10;
        frame[y * WIDTH + x] =
          44
          + corticalBand * 52
          - ventricle * 29
          + eventWave * 55
          + horizontalBand
          + deterministicNoise
          + slowIllumination;
      }
    }
    return frame;
  }

  function translateFrame(frame, offsetX, offsetY) {
    const output = new Float32Array(frame.length);
    for (let y = 0; y < HEIGHT; y += 1) {
      for (let x = 0; x < WIDTH; x += 1) {
        const sourceX = clamp(Math.round(x + offsetX), 0, WIDTH - 1);
        const sourceY = clamp(Math.round(y + offsetY), 0, HEIGHT - 1);
        output[y * WIDTH + x] = frame[sourceY * WIDTH + sourceX];
      }
    }
    return output;
  }

  function removeHorizontalBars(frame) {
    const rowMedians = new Float32Array(HEIGHT);
    const row = new Float32Array(WIDTH);
    for (let y = 0; y < HEIGHT; y += 1) {
      row.set(frame.subarray(y * WIDTH, (y + 1) * WIDTH));
      row.sort();
      rowMedians[y] = row[Math.floor(WIDTH / 2)];
    }
    const sortedMedians = Float32Array.from(rowMedians);
    sortedMedians.sort();
    const globalMedian = sortedMedians[Math.floor(HEIGHT / 2)];
    const output = new Float32Array(frame.length);
    for (let y = 0; y < HEIGHT; y += 1) {
      const correction = rowMedians[y] - globalMedian;
      for (let x = 0; x < WIDTH; x += 1) {
        output[y * WIDTH + x] = frame[y * WIDTH + x] - correction;
      }
    }
    return output;
  }

  function smoothFrame(frame) {
    // Three-tap approximation of the desktop app's light sigma=0.5 Gaussian blur.
    const weights = [0.1065, 0.787, 0.1065];
    const horizontal = new Float32Array(frame.length);
    const output = new Float32Array(frame.length);
    for (let y = 0; y < HEIGHT; y += 1) {
      for (let x = 0; x < WIDTH; x += 1) {
        let total = 0;
        for (let kernel = -1; kernel <= 1; kernel += 1) {
          const sourceX = clamp(x + kernel, 0, WIDTH - 1);
          total += frame[y * WIDTH + sourceX] * weights[kernel + 1];
        }
        horizontal[y * WIDTH + x] = total;
      }
    }
    for (let y = 0; y < HEIGHT; y += 1) {
      for (let x = 0; x < WIDTH; x += 1) {
        let total = 0;
        for (let kernel = -1; kernel <= 1; kernel += 1) {
          const sourceY = clamp(y + kernel, 0, HEIGHT - 1);
          total += horizontal[sourceY * WIDTH + x] * weights[kernel + 1];
        }
        output[y * WIDTH + x] = total;
      }
    }
    return output;
  }

  function processSpatially(frame, options, globalIndex, scopeStart) {
    let output = frame;
    if (options.stabilization) {
      const offsetX =
        Math.sin(globalIndex * 0.58) * 3.4
        - Math.sin(scopeStart * 0.58) * 3.4;
      const offsetY =
        Math.cos(globalIndex * 0.43) * 2.3
        - Math.cos(scopeStart * 0.43) * 2.3;
      output = translateFrame(output, offsetX, offsetY);
    }
    if (options.horizontalBarDenoise) output = removeHorizontalBars(output);
    if (options.smoothing) output = smoothFrame(output);
    return output;
  }

  function medianBaseline(frames) {
    if (!frames.length) return null;
    const output = new Float32Array(WIDTH * HEIGHT);
    const values = new Float32Array(frames.length);
    for (let pixel = 0; pixel < output.length; pixel += 1) {
      for (let index = 0; index < frames.length; index += 1) values[index] = frames[index][pixel];
      values.sort();
      const midpoint = Math.floor(values.length / 2);
      output[pixel] =
        values.length % 2
          ? values[midpoint]
          : (values[midpoint - 1] + values[midpoint]) / 2;
    }
    return output;
  }

  function subtractFrame(frame, baseline) {
    if (!baseline) return frame;
    const output = new Float32Array(frame.length);
    for (let index = 0; index < frame.length; index += 1) {
      output[index] = frame[index] - baseline[index];
    }
    return output;
  }

  function percentileBounds(values) {
    const sorted = Array.from(values).sort((left, right) => left - right);
    if (!sorted.length) return [0, 1];
    const percentile = (fraction) => {
      const position = (sorted.length - 1) * fraction;
      const lower = Math.floor(position);
      const upper = Math.ceil(position);
      const blend = position - lower;
      return sorted[lower] * (1 - blend) + sorted[upper] * blend;
    };
    const low = percentile(0.01);
    const high = percentile(0.99);
    return high > low ? [low, high] : [low, low + 1e-8];
  }

  function minMaxBounds(values) {
    let low = Infinity;
    let high = -Infinity;
    for (let index = 0; index < values.length; index += 1) {
      low = Math.min(low, values[index]);
      high = Math.max(high, values[index]);
    }
    if (!Number.isFinite(low) || !Number.isFinite(high)) return [0, 1];
    return high > low ? [low, high] : [low, low + 1e-8];
  }

  function drawFrame(canvas, frame, bounds) {
    const context = canvas.getContext("2d");
    const image = context.createImageData(WIDTH, HEIGHT);
    const low = bounds[0];
    const span = Math.max(1e-8, bounds[1] - low);
    for (let index = 0; index < frame.length; index += 1) {
      const value = Math.round(clamp((frame[index] - low) / span, 0, 1) * 255);
      const outputIndex = index * 4;
      image.data[outputIndex] = value;
      image.data[outputIndex + 1] = value;
      image.data[outputIndex + 2] = value;
      image.data[outputIndex + 3] = 255;
    }
    context.putImageData(image, 0, 0);
  }

  function computePreview(requestedBaseline, options) {
    const scopeStart = Math.max(0, EVENT_START - requestedBaseline);
    const scopeIndices = [];
    for (let index = scopeStart; index <= EVENT_END; index += 1) scopeIndices.push(index);
    const localEventStart = EVENT_START - scopeStart;
    const effectiveBaseline = Math.min(requestedBaseline, localEventStart);
    const spatialFrames = scopeIndices.map((globalIndex) =>
      processSpatially(createFrame(globalIndex), options, globalIndex, scopeStart)
    );
    const baseline = options.baselineSubtraction
      ? medianBaseline(spatialFrames.slice(0, effectiveBaseline))
      : null;
    const preparedFrames = spatialFrames.map((frame) => subtractFrame(frame, baseline));
    let bounds;
    if (options.globalNormalization) {
      const samples = [];
      for (let index = 0; index < preparedFrames.length; index += 5) {
        const frame = preparedFrames[index];
        for (let pixel = 0; pixel < frame.length; pixel += 8) samples.push(frame[pixel]);
      }
      bounds = percentileBounds(samples);
    } else {
      bounds = minMaxBounds(preparedFrames[localEventStart]);
    }
    return {
      bounds,
      effectiveBaseline,
      frame: preparedFrames[localEventStart],
      scopeStart,
    };
  }

  function checkbox(id, label, checked) {
    const wrapper = document.createElement("label");
    wrapper.className = "swell-open-analysis-demo__check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = id;
    input.checked = checked;
    const text = document.createElement("span");
    text.textContent = label;
    wrapper.append(input, text);
    return { wrapper, input };
  }

  class OpenAnalysisDemo {
    constructor(root) {
      this.root = root;
      this.previewGeneration = 0;
    }

    initialize() {
      this.buildInterface();
      this.bindInteractions();
      const raw = createFrame(EVENT_START);
      drawFrame(this.rawCanvas, raw, percentileBounds(raw));
      this.markStale("Adjust settings, then click “Show Preview”.");
    }

    buildInterface() {
      this.root.innerHTML = "";
      const shell = document.createElement("section");
      shell.className = "swell-open-analysis-demo__shell";
      shell.setAttribute("aria-label", "Simulated Open Analysis preprocessing preview");
      this.shell = shell;

      const summary = document.createElement("div");
      summary.className = "swell-open-analysis-demo__summary";
      const range = document.createElement("strong");
      range.textContent = "Event range: 13 – 21";
      const baselineLabel = document.createElement("label");
      baselineLabel.className = "swell-open-analysis-demo__baseline";
      baselineLabel.textContent = "Baseline Frames";
      this.baselineInput = document.createElement("input");
      this.baselineInput.type = "number";
      this.baselineInput.min = "1";
      this.baselineInput.step = "1";
      this.baselineInput.inputMode = "numeric";
      this.baselineInput.value = String(DEFAULT_BASELINE);
      this.baselineInput.setAttribute("aria-describedby", "swell-open-analysis-baseline-note");
      baselineLabel.append(this.baselineInput);
      summary.append(range, baselineLabel);

      const preprocessing = document.createElement("fieldset");
      preprocessing.className = "swell-open-analysis-demo__options";
      const legend = document.createElement("legend");
      legend.textContent = "Preprocessing";
      preprocessing.appendChild(legend);
      const definitions = [
        ["horizontalBarDenoise", "Horizontal Bar Denoise"],
        ["smoothing", "Smoothing"],
        ["baselineSubtraction", "Baseline Subtraction"],
        ["globalNormalization", "Global Normalization"],
        ["stabilization", "Stabilize"],
      ];
      this.controls = {};
      definitions.forEach(([key, label]) => {
        const control = checkbox(`swell-open-analysis-${key}`, label, DEFAULTS[key]);
        this.controls[key] = control.input;
        preprocessing.appendChild(control.wrapper);
      });

      const preview = document.createElement("div");
      preview.className = "swell-open-analysis-demo__preview";
      const originalFigure = this.makeFigure("Event-start source", "Raw simulated event-start frame");
      this.rawCanvas = originalFigure.canvas;
      const preparedFigure = this.makeFigure("Prepared preview", "Simulated prepared event-start frame");
      this.previewCanvas = preparedFigure.canvas;
      this.placeholder = document.createElement("span");
      this.placeholder.className = "swell-open-analysis-demo__placeholder";
      this.placeholder.textContent = "Click “Show Preview”";
      preparedFigure.frame.appendChild(this.placeholder);
      preview.append(originalFigure.figure, preparedFigure.figure);

      const reasoning = document.createElement("div");
      reasoning.className = "swell-open-analysis-demo__reasoning";
      this.baselineNote = document.createElement("p");
      this.baselineNote.id = "swell-open-analysis-baseline-note";
      this.pipeline = document.createElement("ol");
      this.pipeline.className = "swell-open-analysis-demo__pipeline";
      reasoning.append(this.baselineNote, this.pipeline);

      const footer = document.createElement("div");
      footer.className = "swell-open-analysis-demo__footer";
      this.status = document.createElement("p");
      this.status.setAttribute("aria-live", "polite");
      this.previewButton = document.createElement("button");
      this.previewButton.type = "button";
      this.previewButton.textContent = "Show Preview";
      footer.append(this.status, this.previewButton);

      shell.append(summary, preprocessing, preview, reasoning, footer);
      this.root.appendChild(shell);
    }

    makeFigure(captionText, ariaLabel) {
      const figure = document.createElement("figure");
      figure.className = "swell-open-analysis-demo__figure";
      const frame = document.createElement("div");
      frame.className = "swell-open-analysis-demo__canvas-frame";
      const canvas = document.createElement("canvas");
      canvas.width = WIDTH;
      canvas.height = HEIGHT;
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", ariaLabel);
      canvas.textContent = ariaLabel;
      const caption = document.createElement("figcaption");
      caption.textContent = captionText;
      frame.appendChild(canvas);
      figure.append(frame, caption);
      return { canvas, caption, figure, frame };
    }

    readBaseline() {
      const parsed = Math.trunc(Number(this.baselineInput.value));
      return Number.isFinite(parsed) ? Math.max(1, parsed) : DEFAULT_BASELINE;
    }

    readOptions() {
      return Object.fromEntries(
        Object.entries(this.controls).map(([key, input]) => [key, input.checked])
      );
    }

    bindInteractions() {
      this.previewButton.addEventListener("click", () => this.refreshPreview());
      this.baselineInput.addEventListener("input", () =>
        this.markStale("Settings changed — click “Show Preview” to update.")
      );
      Object.values(this.controls).forEach((input) => {
        input.addEventListener("change", () =>
          this.markStale("Settings changed — click “Show Preview” to update.")
        );
      });
    }

    markStale(message) {
      this.previewGeneration += 1;
      this.shell.removeAttribute("aria-busy");
      this.previewButton.disabled = false;
      this.status.textContent = message;
      this.status.classList.add("is-stale");
      this.placeholder.hidden = false;
      this.previewCanvas.classList.add("is-stale");
      this.updateReasoning(this.readBaseline(), this.readOptions(), null);
    }

    refreshPreview() {
      const generation = this.previewGeneration + 1;
      this.previewGeneration = generation;
      const baseline = this.readBaseline();
      this.baselineInput.value = String(baseline);
      const options = this.readOptions();
      this.previewButton.disabled = true;
      this.shell.setAttribute("aria-busy", "true");
      this.status.classList.remove("is-stale");
      this.status.textContent = "Preparing simulated preview…";
      window.setTimeout(() => {
        if (generation !== this.previewGeneration || !this.root.isConnected) return;
        const result = computePreview(baseline, options);
        drawFrame(this.previewCanvas, result.frame, result.bounds);
        this.previewCanvas.classList.remove("is-stale");
        this.placeholder.hidden = true;
        this.previewButton.disabled = false;
        this.shell.removeAttribute("aria-busy");
        this.status.textContent = "Preview updated.";
        this.updateReasoning(baseline, options, result);
      }, 120);
    }

    updateReasoning(requestedBaseline, options, result) {
      const available = EVENT_START;
      const effective = result
        ? result.effectiveBaseline
        : Math.min(requestedBaseline, available);
      const scopeStart = result
        ? result.scopeStart
        : Math.max(0, EVENT_START - requestedBaseline);
      if (requestedBaseline > available) {
        this.baselineNote.innerHTML =
          `<strong>${requestedBaseline} requested; ${available} available.</strong> `
          + `Swell uses ${effective} preceding frames and never borrows from the event. `
          + `Prepared scope: frames ${scopeStart + 1}–${EVENT_END + 1}.`;
      } else {
        this.baselineNote.innerHTML =
          `<strong>${effective} preceding frames will be used.</strong> `
          + `Prepared scope: frames ${scopeStart + 1}–${EVENT_END + 1}.`;
      }

      const stages = [
        [
          options.stabilization,
          "Stabilize",
          options.stabilization
            ? "Align frames to the first frame in the prepared scope."
            : "Skipped; original image coordinates are retained.",
        ],
        [
          options.horizontalBarDenoise,
          "Horizontal Bar Denoise",
          options.horizontalBarDenoise
            ? "Correct each row’s median bias."
            : "Skipped; horizontal banding remains.",
        ],
        [
          options.smoothing,
          "Smoothing",
          options.smoothing
            ? "Apply light spatial smoothing."
            : "Skipped; fine noise remains.",
        ],
        [
          options.baselineSubtraction,
          "Baseline Subtraction",
          options.baselineSubtraction
            ? `Subtract the pixelwise median of ${effective} preceding frames.`
            : "Skipped; earlier context can still inform stabilization and global scaling.",
        ],
        [
          options.globalNormalization,
          "Global Normalization",
          options.globalNormalization
            ? "Use one robust intensity range sampled across the prepared scope."
            : "Scale this displayed frame from its own intensity range.",
        ],
      ];
      this.pipeline.innerHTML = "";
      stages.forEach(([enabled, title, description]) => {
        const item = document.createElement("li");
        item.className = enabled ? "is-active" : "is-skipped";
        const heading = document.createElement("strong");
        heading.textContent = title;
        const state = document.createElement("span");
        state.textContent = enabled ? "On" : "Off";
        const text = document.createElement("small");
        text.textContent = description;
        item.append(heading, state, text);
        this.pipeline.appendChild(item);
      });
    }
  }

  function mountOpenAnalysisDemos() {
    document.querySelectorAll("[data-swell-open-analysis-demo]").forEach((root) => {
      if (root.dataset.swellOpenAnalysisMounted === "true") return;
      root.dataset.swellOpenAnalysisMounted = "true";
      try {
        const demo = new OpenAnalysisDemo(root);
        root.swellOpenAnalysisDemo = demo;
        demo.initialize();
      } catch (error) {
        root.innerHTML =
          `<p class="swell-open-analysis-demo__fallback">`
          + `Preprocessing preview unavailable: ${error.message}</p>`;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountOpenAnalysisDemos, { once: true });
  } else {
    mountOpenAnalysisDemos();
  }
  if (typeof document$ !== "undefined") document$.subscribe(mountOpenAnalysisDemos);
}());
