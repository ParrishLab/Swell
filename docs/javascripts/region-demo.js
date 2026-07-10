(function () {
  "use strict";

  const VIEW_WIDTH = 792;
  const VIEW_HEIGHT = 612;
  const MASK_WIDTH = 396;
  const MASK_HEIGHT = 306;
  const MASK_SCALE = MASK_WIDTH / VIEW_WIDTH;
  const FRAME_COUNT = 7;
  const MASK_BLUE = [27, 117, 188];
  const SEQUENCE_MASK_SCALE = 1.16;
  const SEQUENCE_FILES = ["002122", "002123", "002124", "002125", "002126", "002127", "002128"];

  const TOOLS = [
    { id: "select", label: "Select (V)", icon: "Mouse Icon@4x.png", description: "Select a saved region, then drag its vertices or interior to reshape it." },
    { id: "include", label: "Include Region (R)", icon: "Region+ Icon@4x.png", description: "Click three or more vertices around tissue that must be included in the final mask." },
    { id: "exclude", label: "Exclude Region (Shift+R)", icon: "Region- Icon@4x.png", description: "Click three or more vertices over unwanted mask spill. Exclude takes precedence over include." },
  ];

  const CLEAR_TOOL = { id: "clear", label: "Clear Frame", icon: "Clear Frame Icon@4x.png", description: "Remove the draft and both saved regions from this simulated exercise." };

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function countMask(mask) {
    let count = 0;
    for (let index = 0; index < mask.length; index += 1) count += mask[index];
    return count;
  }

  function combineMasks(left, right, operation) {
    const output = new Uint8Array(left.length);
    for (let index = 0; index < output.length; index += 1) {
      if (operation === "union") output[index] = left[index] || right[index] ? 1 : 0;
      if (operation === "subtract") output[index] = left[index] && !right[index] ? 1 : 0;
      if (operation === "intersect") output[index] = left[index] && right[index] ? 1 : 0;
    }
    return output;
  }

  function maskFromCanvas(canvas) {
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const pixels = context.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    const mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let index = 0; index < mask.length; index += 1) mask[index] = pixels[index * 4 + 3] > 0 ? 1 : 0;
    return mask;
  }

  function maskFromBinaryImage(image) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(image, 0, 0, MASK_WIDTH, MASK_HEIGHT);
    const pixels = context.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    const mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let index = 0; index < mask.length; index += 1) mask[index] = pixels[index * 4] > 127 ? 1 : 0;
    return mask;
  }

  function scaleMaskAroundCentroid(mask, scale) {
    let totalX = 0;
    let totalY = 0;
    let count = 0;
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        if (!mask[y * MASK_WIDTH + x]) continue;
        totalX += x;
        totalY += y;
        count += 1;
      }
    }
    if (!count || scale === 1) return new Uint8Array(mask);
    const centerX = totalX / count;
    const centerY = totalY / count;
    const output = new Uint8Array(mask.length);
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        const sourceX = Math.round(centerX + (x - centerX) / scale);
        const sourceY = Math.round(centerY + (y - centerY) / scale);
        if (sourceX < 0 || sourceX >= MASK_WIDTH || sourceY < 0 || sourceY >= MASK_HEIGHT) continue;
        output[y * MASK_WIDTH + x] = mask[sourceY * MASK_WIDTH + sourceX];
      }
    }
    return output;
  }

  function translateMask(mask, offsetX, offsetY) {
    const output = new Uint8Array(mask.length);
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        const sourceX = x - offsetX;
        const sourceY = y - offsetY;
        if (sourceX < 0 || sourceX >= MASK_WIDTH || sourceY < 0 || sourceY >= MASK_HEIGHT) continue;
        output[y * MASK_WIDTH + x] = mask[sourceY * MASK_WIDTH + sourceX];
      }
    }
    return output;
  }

  function alignMaskToWhiteMatter(mask, whiteMatterMask) {
    for (let offsetY = 0; offsetY < MASK_HEIGHT; offsetY += 1) {
      const shifted = translateMask(mask, 0, offsetY);
      if (countMask(combineMasks(shifted, whiteMatterMask, "intersect"))) {
        return shifted;
      }
    }
    return new Uint8Array(mask);
  }

  function expandingWhiteMatterSpill(whiteMatterMask, frameIndex) {
    const lowerEdge = 262 + frameIndex * 6;
    const spillBoundary = rasterizePolygon([
      { x: 400, y: 230 },
      { x: 488, y: 238 },
      { x: 496, y: lowerEdge - 5 },
      { x: 426, y: lowerEdge },
    ]);
    return combineMasks(whiteMatterMask, spillBoundary, "intersect");
  }

  function rasterizePath(pathData) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.setTransform(MASK_SCALE, 0, 0, MASK_SCALE, 0, 0);
    context.fill(new Path2D(pathData));
    return maskFromCanvas(canvas);
  }

  function rasterizePolygon(points) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.setTransform(MASK_SCALE, 0, 0, MASK_SCALE, 0, 0);
    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) context.moveTo(point.x, point.y);
      else context.lineTo(point.x, point.y);
    });
    context.closePath();
    context.fill();
    return maskFromCanvas(canvas);
  }

  function filledPathNodes(documentNode) {
    const nonFilledClasses = new Set();
    documentNode.querySelectorAll("style").forEach((style) => {
      const matches = style.textContent.matchAll(/\.([-\w]+)\s*\{[^}]*\bfill\s*:\s*none\b[^}]*\}/gi);
      for (const match of matches) nonFilledClasses.add(match[1]);
    });
    return Array.from(documentNode.querySelectorAll("path[d]")).filter((node) => {
      const classes = String(node.getAttribute("class") || "").split(/\s+/);
      return !classes.some((className) => nonFilledClasses.has(className));
    });
  }

  function eraseDisc(mask, point, radius) {
    const centerX = Math.floor(point.x * MASK_SCALE);
    const centerY = Math.floor(point.y * MASK_SCALE);
    const scaledRadius = radius * MASK_SCALE;
    for (let y = Math.max(0, Math.floor(centerY - scaledRadius)); y <= Math.min(MASK_HEIGHT - 1, Math.ceil(centerY + scaledRadius)); y += 1) {
      for (let x = Math.max(0, Math.floor(centerX - scaledRadius)); x <= Math.min(MASK_WIDTH - 1, Math.ceil(centerX + scaledRadius)); x += 1) {
        if ((x - centerX) ** 2 + (y - centerY) ** 2 <= scaledRadius ** 2) mask[y * MASK_WIDTH + x] = 0;
      }
    }
  }

  function distanceToSegment(point, start, end) {
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    const denominator = dx * dx + dy * dy;
    const t = denominator === 0 ? 0 : clamp(((point.x - start.x) * dx + (point.y - start.y) * dy) / denominator, 0, 1);
    return Math.hypot(point.x - (start.x + dx * t), point.y - (start.y + dy * t));
  }

  function pointInPolygon(point, points) {
    let inside = false;
    for (let index = 0, previous = points.length - 1; index < points.length; previous = index, index += 1) {
      const current = points[index];
      const prior = points[previous];
      const crosses = (current.y > point.y) !== (prior.y > point.y);
      if (crosses && point.x < (prior.x - current.x) * (point.y - current.y) / (prior.y - current.y) + current.x) inside = !inside;
    }
    return inside;
  }

  class RegionDemo {
    constructor(root) {
      this.root = root;
      this.tool = "include";
      this.frame = 0;
      this.baseMasks = [];
      this.regions = [];
      this.draft = null;
      this.selectedId = null;
      this.drag = null;
      this.sourceImage = null;
      this.buttons = new Map();
    }

    async initialize() {
      this.buildInterface();
      const svgUrl = new URL(this.root.dataset.svgSrc, window.location.href);
      const response = await fetch(svgUrl);
      if (!response.ok) throw new Error(`Unable to load slice SVG (${response.status}).`);
      const svgText = await response.text();
      const documentNode = new DOMParser().parseFromString(svgText, "image/svg+xml");
      if (documentNode.querySelector("parsererror")) throw new Error("Unable to parse slice SVG.");
      await this.loadSourceImage(svgText);
      this.prepareBaseMask(documentNode);
      await this.loadMaskSequence();
      this.bindInteractions();
      this.setTool("include");
      this.announce("Persistent-regions demo ready. Draw an Include Region around the missed cortical area.");
    }

    buildInterface() {
      const iconBase = new URL(this.root.dataset.iconBase, window.location.href);
      this.root.innerHTML = "";
      this.shell = document.createElement("div");
      this.shell.className = "swell-region-demo__shell";
      this.stage = document.createElement("div");
      this.stage.className = "swell-region-demo__stage";
      this.canvas = document.createElement("canvas");
      this.canvas.className = "swell-region-demo__canvas";
      this.canvas.width = VIEW_WIDTH;
      this.canvas.height = VIEW_HEIGHT;
      this.canvas.tabIndex = 0;
      this.canvas.setAttribute("aria-label", "Interactive persistent-regions viewer");
      this.context = this.canvas.getContext("2d");
      this.rail = document.createElement("div");
      this.rail.className = "swell-region-demo__rail";
      this.rail.setAttribute("role", "toolbar");
      this.rail.setAttribute("aria-label", "Persistent region tools");
      TOOLS.forEach((definition) => {
        const button = this.makeToolButton(definition, new URL(definition.icon, iconBase));
        this.buttons.set(definition.id, button);
        this.rail.appendChild(button);
      });
      const clearButton = this.makeToolButton(CLEAR_TOOL, new URL(CLEAR_TOOL.icon, iconBase));
      clearButton.classList.add("swell-region-demo__tool--clear");
      clearButton.removeAttribute("aria-pressed");
      this.rail.appendChild(clearButton);
      this.status = document.createElement("p");
      this.status.className = "swell-region-demo__sr-status";
      this.status.setAttribute("aria-live", "polite");
      this.stage.append(this.canvas, this.rail, this.status);

      this.toolHelp = document.createElement("p");
      this.toolHelp.className = "swell-region-demo__tool-help";
      this.toolHelp.setAttribute("aria-live", "polite");

      this.controls = document.createElement("div");
      this.controls.className = "swell-region-demo__controls";
      const frameLabel = document.createElement("label");
      frameLabel.textContent = "Viewing frame";
      frameLabel.htmlFor = "swell-region-demo-frame";
      this.frameInput = document.createElement("input");
      this.frameInput.id = "swell-region-demo-frame";
      this.frameInput.type = "range";
      this.frameInput.min = "1";
      this.frameInput.max = String(FRAME_COUNT);
      this.frameInput.value = "1";
      this.frameInput.setAttribute("aria-label", "Current frame");
      this.frameValue = document.createElement("output");
      this.frameInput.addEventListener("input", () => {
        this.frame = Number(this.frameInput.value) - 1;
        if (!this.draft && !this.selectedRegion()) this.setRangeInputs(this.frame, this.frame);
        this.render();
      });
      const rangeLabel = document.createElement("span");
      rangeLabel.textContent = "Region frames (start-end)";
      this.startInput = this.makeNumberInput("Region start frame");
      this.endInput = this.makeNumberInput("Region end frame");
      this.startInput.value = "1";
      this.endInput.value = "1";
      const rangeChange = () => this.applyRangeInputs();
      this.startInput.addEventListener("change", rangeChange);
      this.endInput.addEventListener("change", rangeChange);
      this.closeButton = this.commandButton("Close Shape", () => this.closeDraft());
      this.discardButton = this.commandButton("Discard", () => this.discardDraft());
      this.addButton = this.commandButton("Add Region", () => this.addRegion());
      this.controls.append(frameLabel, this.frameInput, this.frameValue, rangeLabel, this.startInput, this.endInput, this.closeButton, this.discardButton, this.addButton);

      this.regionPanel = document.createElement("div");
      this.regionPanel.className = "swell-region-demo__panel";
      this.shell.append(this.stage, this.toolHelp, this.controls, this.regionPanel);
      this.root.appendChild(this.shell);
    }

    makeNumberInput(label) {
      const input = document.createElement("input");
      input.type = "number";
      input.min = "1";
      input.max = String(FRAME_COUNT);
      input.value = "1";
      input.setAttribute("aria-label", label);
      return input;
    }

    commandButton(label, command) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", command);
      return button;
    }

    makeToolButton(definition, iconUrl) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "swell-region-demo__tool";
      button.dataset.tool = definition.id;
      button.title = definition.label;
      button.setAttribute("aria-label", definition.label);
      if (definition.id !== "clear") button.setAttribute("aria-pressed", "false");
      const image = document.createElement("img");
      image.src = iconUrl.href;
      image.alt = "";
      button.appendChild(image);
      button.addEventListener("click", () => {
        if (definition.id === "clear") {
          this.clearAll();
          this.updateToolHelp(definition);
        }
        else this.setTool(definition.id);
        this.canvas.focus();
      });
      return button;
    }

    async loadSourceImage(svgText) {
      const blobUrl = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" }));
      try {
        this.sourceImage = new Image();
        await new Promise((resolve, reject) => {
          this.sourceImage.onload = resolve;
          this.sourceImage.onerror = () => reject(new Error("Unable to render slice SVG."));
          this.sourceImage.src = blobUrl;
        });
      } finally {
        URL.revokeObjectURL(blobUrl);
      }
    }

    async loadMaskSequence() {
      const baseUrl = new URL(this.root.dataset.maskBase, window.location.href);
      const masks = await Promise.all(SEQUENCE_FILES.map(async (file) => {
        const image = new Image();
        await new Promise((resolve, reject) => {
          image.onload = resolve;
          image.onerror = () => reject(new Error(`Unable to load simulated mask frame ${file}.`));
          image.src = new URL(`${file}.png`, baseUrl).href;
        });
        return alignMaskToWhiteMatter(
          scaleMaskAroundCentroid(maskFromBinaryImage(image), SEQUENCE_MASK_SCALE),
          this.whiteMatterMask,
        );
      }));
      this.baseMasks = masks.map((mask, index) => {
        const corticalMask = combineMasks(mask, this.corticalMask, "intersect");
        eraseDisc(corticalMask, { x: 570 + index * 4, y: 205 + index * 2 }, 21);
        return combineMasks(
          corticalMask,
          expandingWhiteMatterSpill(this.whiteMatterMask, index),
          "union",
        );
      });
      if (this.baseMasks.some((mask) => countMask(mask) === 0)) throw new Error("A simulated mask frame does not overlap the tutorial slice.");
    }

    prepareBaseMask(documentNode) {
      const pathNodes = filledPathNodes(documentNode);
      const rawMasks = pathNodes.map((node) => rasterizePath(node.getAttribute("d")));
      const visibleMasks = rawMasks.map((mask, index) => {
        let visible = new Uint8Array(mask);
        for (let later = index + 1; later < rawMasks.length; later += 1) visible = combineMasks(visible, rawMasks[later], "subtract");
        return visible;
      });
      const sdIndex = pathNodes.findIndex((node) => node.getAttribute("class") === "cls-5");
      const whiteMatterIndex = pathNodes.findIndex((node) => node.getAttribute("class") === "cls-1");
      if (sdIndex === -1 || whiteMatterIndex === -1) throw new Error("The slice SVG is missing required tissue regions.");
      this.corticalMask = new Uint8Array(visibleMasks[sdIndex]);
      this.whiteMatterMask = new Uint8Array(visibleMasks[whiteMatterIndex]);
    }

    bindInteractions() {
      this.canvas.addEventListener("pointerdown", (event) => this.onPointerDown(event));
      this.canvas.addEventListener("pointermove", (event) => this.onPointerMove(event));
      this.canvas.addEventListener("pointerup", () => this.endDrag());
      this.canvas.addEventListener("pointercancel", () => this.endDrag());
      this.canvas.addEventListener("keydown", (event) => this.onKeyDown(event));
    }

    setTool(tool) {
      if ((tool === "include" || tool === "exclude") && this.hasMode(tool)) {
        this.announce(`The ${tool} region slot is already occupied. Select, edit, or delete it before creating another.`);
        return;
      }
      this.tool = tool;
      this.buttons.forEach((button, id) => button.setAttribute("aria-pressed", id === tool ? "true" : "false"));
      this.canvas.style.cursor = tool === "select" ? "default" : "crosshair";
      this.selectedId = tool === "select" ? this.selectedId : null;
      this.updateToolHelp(TOOLS.find((definition) => definition.id === tool));
      this.render();
    }

    updateToolHelp(definition) {
      if (definition) this.toolHelp.textContent = definition.description;
    }

    pointFromEvent(event) {
      const rect = this.canvas.getBoundingClientRect();
      return {
        x: clamp((event.clientX - rect.left) * VIEW_WIDTH / rect.width, 0, VIEW_WIDTH),
        y: clamp((event.clientY - rect.top) * VIEW_HEIGHT / rect.height, 0, VIEW_HEIGHT),
      };
    }

    onPointerDown(event) {
      event.preventDefault();
      this.canvas.focus();
      const point = this.pointFromEvent(event);
      if (this.tool === "include" || this.tool === "exclude") {
        this.addDraftPoint(point);
        return;
      }
      this.beginRegionDrag(point, event.pointerId);
    }

    addDraftPoint(point) {
      if (!this.draft) this.draft = { mode: this.tool, points: [], closed: false, start: this.frame, end: this.frame };
      if (this.draft.mode !== this.tool) {
        this.announce("Finish or discard the current draft before switching region modes.");
        return;
      }
      if (this.draft.closed) {
        this.announce("This shape is closed. Add it or discard it before placing more vertices.");
        return;
      }
      this.draft.points.push(point);
      this.setRangeInputs(this.draft.start, this.draft.end);
      this.render();
    }

    beginRegionDrag(point, pointerId) {
      const region = this.regionAt(point);
      if (!region) {
        this.selectedId = null;
        this.render();
        return;
      }
      this.selectedId = region.id;
      const vertexIndex = region.points.findIndex((vertex) => Math.hypot(vertex.x - point.x, vertex.y - point.y) <= 14);
      this.drag = vertexIndex >= 0
        ? { type: "vertex", id: region.id, index: vertexIndex }
        : { type: "move", id: region.id, start: point, original: region.points.map((vertex) => ({ ...vertex })) };
      this.canvas.setPointerCapture(pointerId);
      this.setRangeInputs(region.start, region.end);
      this.render();
    }

    onPointerMove(event) {
      if (!this.drag) return;
      event.preventDefault();
      const point = this.pointFromEvent(event);
      const region = this.regionById(this.drag.id);
      if (!region) return;
      if (this.drag.type === "vertex") region.points[this.drag.index] = point;
      else {
        const dx = point.x - this.drag.start.x;
        const dy = point.y - this.drag.start.y;
        region.points = this.drag.original.map((vertex) => ({ x: clamp(vertex.x + dx, 0, VIEW_WIDTH), y: clamp(vertex.y + dy, 0, VIEW_HEIGHT) }));
      }
      this.render();
    }

    endDrag() {
      this.drag = null;
    }

    onKeyDown(event) {
      if (event.key === "r" || event.key === "R") {
        this.setTool(event.shiftKey ? "exclude" : "include");
        event.preventDefault();
      } else if (event.key === "v" || event.key === "V") {
        this.setTool("select");
        event.preventDefault();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        this.deleteSelected();
        event.preventDefault();
      }
    }

    closeDraft() {
      if (!this.draft || this.draft.points.length < 3) {
        this.announce("Place at least three vertices before closing a shape.");
        return;
      }
      this.draft.closed = true;
      this.announce("Shape closed. Choose Add Region to save it.");
      this.render();
    }

    discardDraft() {
      if (!this.draft) return;
      this.draft = null;
      this.setRangeInputs(this.frame, this.frame);
      this.announce("Region draft discarded.");
      this.render();
    }

    addRegion() {
      if (!this.draft || !this.draft.closed) {
        this.announce("Close a shape with at least three vertices before adding it.");
        return;
      }
      if (this.hasMode(this.draft.mode)) {
        this.announce(`Only one ${this.draft.mode} region is available in this exercise.`);
        return;
      }
      const region = { id: `${this.draft.mode}-${Date.now()}`, mode: this.draft.mode, points: this.draft.points.map((point) => ({ ...point })), start: this.draft.start, end: this.draft.end, enabled: true };
      this.regions.push(region);
      this.selectedId = region.id;
      this.draft = null;
      this.setTool("select");
      this.setRangeInputs(region.start, region.end);
      this.announce(`${region.mode === "include" ? "Include" : "Exclude"} Region added.`);
      this.render();
    }

    applyRangeInputs() {
      const start = clamp(Number(this.startInput.value || 1) - 1, 0, FRAME_COUNT - 1);
      const end = clamp(Number(this.endInput.value || 1) - 1, 0, FRAME_COUNT - 1);
      const normalizedStart = Math.min(start, end);
      const normalizedEnd = Math.max(start, end);
      const target = this.draft || this.selectedRegion();
      if (target) {
        target.start = normalizedStart;
        target.end = normalizedEnd;
      }
      this.setRangeInputs(normalizedStart, normalizedEnd);
      this.render();
    }

    setRangeInputs(start, end) {
      this.startInput.value = String(start + 1);
      this.endInput.value = String(end + 1);
    }

    clearAll() {
      this.regions = [];
      this.draft = null;
      this.selectedId = null;
      this.setRangeInputs(this.frame, this.frame);
      this.announce("All simulated regions were cleared.");
      this.render();
    }

    deleteSelected() {
      if (!this.selectedId) return;
      this.regions = this.regions.filter((region) => region.id !== this.selectedId);
      this.selectedId = null;
      this.setRangeInputs(this.frame, this.frame);
      this.announce("Selected region deleted.");
      this.render();
    }

    selectedRegion() {
      return this.regionById(this.selectedId);
    }

    regionById(id) {
      return this.regions.find((region) => region.id === id) || null;
    }

    hasMode(mode) {
      return this.regions.some((region) => region.mode === mode);
    }

    regionAt(point) {
      const ordered = [...this.regions].sort((left, right) => (right.id === this.selectedId) - (left.id === this.selectedId));
      for (const region of ordered) {
        if (region.points.some((vertex) => Math.hypot(vertex.x - point.x, vertex.y - point.y) <= 14)) return region;
        if (region.points.some((vertex, index) => distanceToSegment(point, vertex, region.points[(index + 1) % region.points.length]) <= 9)) return region;
        if (pointInPolygon(point, region.points)) return region;
      }
      return null;
    }

    active(region) {
      return region.enabled && region.start <= this.frame && this.frame <= region.end;
    }

    composeMask() {
      let mask = new Uint8Array(this.baseMasks[this.frame]);
      this.regions.filter((region) => this.active(region) && region.mode === "include").forEach((region) => {
        mask = combineMasks(mask, rasterizePolygon(region.points), "union");
      });
      this.regions.filter((region) => this.active(region) && region.mode === "exclude").forEach((region) => {
        mask = combineMasks(mask, rasterizePolygon(region.points), "subtract");
      });
      return mask;
    }

    render() {
      this.context.clearRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.fillStyle = "#0f1318";
      this.context.fillRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      if (this.sourceImage) this.context.drawImage(this.sourceImage, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.drawMask(this.composeMask());
      this.regions.forEach((region) => this.drawRegion(region, this.active(region)));
      if (this.draft) this.drawDraft();
      this.frameValue.textContent = `${this.frame + 1} / ${FRAME_COUNT}`;
      this.refreshControls();
      this.refreshRegionPanel();
    }

    drawMask(mask) {
      const overlay = document.createElement("canvas");
      overlay.width = MASK_WIDTH;
      overlay.height = MASK_HEIGHT;
      const context = overlay.getContext("2d");
      const image = context.createImageData(MASK_WIDTH, MASK_HEIGHT);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          const index = y * MASK_WIDTH + x;
          if (!mask[index]) continue;
          const edge = x === 0 || y === 0 || x === MASK_WIDTH - 1 || y === MASK_HEIGHT - 1 || !mask[index - 1] || !mask[index + 1] || !mask[index - MASK_WIDTH] || !mask[index + MASK_WIDTH];
          const pixel = index * 4;
          image.data[pixel] = MASK_BLUE[0];
          image.data[pixel + 1] = MASK_BLUE[1];
          image.data[pixel + 2] = MASK_BLUE[2];
          image.data[pixel + 3] = edge ? 235 : 92;
        }
      }
      context.putImageData(image, 0, 0);
      this.context.save();
      this.context.imageSmoothingEnabled = false;
      this.context.drawImage(overlay, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.restore();
    }

    drawRegion(region, active) {
      const selected = region.id === this.selectedId;
      const color = region.mode === "exclude" ? "#d14343" : "#edf1f3";
      this.context.save();
      this.context.strokeStyle = color;
      this.context.fillStyle = region.mode === "exclude" ? "rgba(209, 67, 67, 0.13)" : "rgba(237, 241, 243, 0.10)";
      this.context.globalAlpha = active || selected ? 1 : 0.35;
      this.context.lineWidth = selected ? 3 : 2;
      if (!active) this.context.setLineDash([7, 6]);
      this.context.beginPath();
      region.points.forEach((point, index) => index === 0 ? this.context.moveTo(point.x, point.y) : this.context.lineTo(point.x, point.y));
      this.context.closePath();
      this.context.fill();
      this.context.stroke();
      if (selected) {
        this.context.setLineDash([]);
        region.points.forEach((point) => {
          this.context.fillStyle = color;
          this.context.fillRect(point.x - 4, point.y - 4, 8, 8);
        });
      }
      this.context.restore();
    }

    drawDraft() {
      const color = this.draft.mode === "exclude" ? "#d14343" : "#edf1f3";
      this.context.save();
      this.context.strokeStyle = color;
      this.context.fillStyle = "rgba(237, 241, 243, 0.08)";
      this.context.lineWidth = 2;
      this.context.setLineDash([6, 5]);
      this.context.beginPath();
      this.draft.points.forEach((point, index) => index === 0 ? this.context.moveTo(point.x, point.y) : this.context.lineTo(point.x, point.y));
      if (this.draft.closed) {
        this.context.closePath();
        this.context.fill();
      }
      this.context.stroke();
      this.context.setLineDash([]);
      this.draft.points.forEach((point) => {
        this.context.beginPath();
        this.context.fillStyle = "#0f1318";
        this.context.arc(point.x, point.y, 5, 0, Math.PI * 2);
        this.context.fill();
        this.context.strokeStyle = color;
        this.context.lineWidth = 2;
        this.context.stroke();
      });
      this.context.restore();
    }

    refreshControls() {
      const selected = this.selectedRegion();
      const draft = this.draft;
      this.closeButton.disabled = !draft || draft.closed || draft.points.length < 3;
      this.discardButton.disabled = !draft;
      this.addButton.disabled = !draft || !draft.closed || this.hasMode(draft.mode);
      this.buttons.get("include").disabled = this.hasMode("include");
      this.buttons.get("exclude").disabled = this.hasMode("exclude");
      if (selected && !draft) this.setRangeInputs(selected.start, selected.end);
      if (draft) this.setRangeInputs(draft.start, draft.end);
    }

    refreshRegionPanel() {
      this.regionPanel.innerHTML = "";
      const title = document.createElement("strong");
      title.textContent = "Regions";
      this.regionPanel.appendChild(title);
      if (!this.regions.length) {
        const empty = document.createElement("span");
        empty.textContent = "No saved regions";
        this.regionPanel.appendChild(empty);
        return;
      }
      this.regions.forEach((region) => {
        const row = document.createElement("div");
        row.className = "swell-region-demo__region-row";
        const select = this.commandButton(`${region.mode === "include" ? "Include" : "Exclude"} ${region.start + 1}-${region.end + 1}`, () => {
          this.selectedId = region.id;
          this.draft = null;
          this.setTool("select");
          this.setRangeInputs(region.start, region.end);
          this.render();
        });
        select.classList.toggle("swell-region-demo__region-row--selected", region.id === this.selectedId);
        const enabledLabel = document.createElement("label");
        const enabled = document.createElement("input");
        enabled.type = "checkbox";
        enabled.checked = region.enabled;
        enabled.setAttribute("aria-label", `${region.mode} region enabled`);
        enabled.addEventListener("change", () => {
          region.enabled = enabled.checked;
          this.render();
        });
        enabledLabel.append(enabled, document.createTextNode(" Enabled"));
        const remove = this.commandButton("Delete", () => {
          this.selectedId = region.id;
          this.deleteSelected();
        });
        row.append(select, enabledLabel, remove);
        this.regionPanel.appendChild(row);
      });
    }

    announce(message) {
      this.status.textContent = message;
    }
  }

  function mountRegionDemos() {
    document.querySelectorAll("[data-swell-region-demo]").forEach((root) => {
      if (root.dataset.swellRegionMounted === "true") return;
      root.dataset.swellRegionMounted = "true";
      const demo = new RegionDemo(root);
      root.swellRegionDemo = demo;
      demo.initialize().catch((error) => {
        root.innerHTML = `<p class="swell-region-demo__fallback">Persistent-regions demo unavailable: ${error.message}</p>`;
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountRegionDemos, { once: true });
  else mountRegionDemos();
  if (typeof document$ !== "undefined") document$.subscribe(mountRegionDemos);
}());
