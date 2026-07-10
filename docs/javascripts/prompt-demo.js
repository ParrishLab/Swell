(function () {
  "use strict";

  const VIEW_WIDTH = 792;
  const VIEW_HEIGHT = 612;
  const MASK_WIDTH = 396;
  const MASK_HEIGHT = 306;
  const MASK_SCALE = MASK_WIDTH / VIEW_WIDTH;
  const MASK_BLUE = [27, 117, 188];

  const TOOL_DEFINITIONS = [
    {
      id: "select",
      label: "Select (V)",
      icon: "Mouse Icon@4x.png",
      description: "Select, move, or delete a point. Drag a box or one of its handles to reposition or resize it.",
    },
    {
      id: "point_pos",
      label: "Add Point (+)",
      icon: "Point+ Icon@4x.png",
      description: "Place positive points on tissue that belongs in the mask. Add points across connected anatomy to include more of it.",
    },
    {
      id: "point_neg",
      label: "Remove Point (-)",
      icon: "Point- Icon@4x.png",
      description: "Place negative points on unwanted mask spill or nearby tissue that should stay excluded.",
    },
    {
      id: "box",
      label: "Box (K)",
      icon: "Box Icon@4x.png",
      description: "Drag one box around the target to favor proposals that fit its bounds. Only one box is used at a time.",
    },
  ];

  const CLEAR_TOOL = {
    id: "clear",
    label: "Clear Frame",
    icon: "Clear Frame Icon@4x.png",
    description: "Remove every point, box, and simulated mask from this frame.",
  };

  function clamp(value, low, high) {
    return Math.max(low, Math.min(high, value));
  }

  function countMask(mask) {
    let count = 0;
    for (let i = 0; i < mask.length; i += 1) count += mask[i];
    return count;
  }

  function combineMasks(left, right, operation) {
    const output = new Uint8Array(left.length);
    for (let i = 0; i < output.length; i += 1) {
      if (operation === "union") output[i] = left[i] || right[i] ? 1 : 0;
      if (operation === "subtract") output[i] = left[i] && !right[i] ? 1 : 0;
      if (operation === "intersect") output[i] = left[i] && right[i] ? 1 : 0;
    }
    return output;
  }

  function morphMask(source, grow, iterations) {
    let current = new Uint8Array(source);
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      const next = new Uint8Array(current.length);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          const index = y * MASK_WIDTH + x;
          let value = grow ? current[index] : 1;
          for (let dy = -1; dy <= 1; dy += 1) {
            for (let dx = -1; dx <= 1; dx += 1) {
              const nx = x + dx;
              const ny = y + dy;
              const neighbor = nx >= 0 && nx < MASK_WIDTH && ny >= 0 && ny < MASK_HEIGHT
                ? current[ny * MASK_WIDTH + nx]
                : 0;
              if (grow && neighbor) value = 1;
              if (!grow && !neighbor) value = 0;
            }
          }
          next[index] = value ? 1 : 0;
        }
      }
      current = next;
    }
    return current;
  }

  function maskBounds(mask) {
    let minX = MASK_WIDTH;
    let minY = MASK_HEIGHT;
    let maxX = -1;
    let maxY = -1;
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        if (!mask[y * MASK_WIDTH + x]) continue;
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
    return maxX >= minX ? { minX, minY, maxX, maxY } : null;
  }

  function maskContains(mask, point) {
    const x = clamp(Math.floor(point.x * MASK_SCALE), 0, MASK_WIDTH - 1);
    const y = clamp(Math.floor(point.y * MASK_SCALE), 0, MASK_HEIGHT - 1);
    return Boolean(mask[y * MASK_WIDTH + x]);
  }

  function normalizedBox(box) {
    if (!box) return null;
    return {
      x0: Math.min(box.x0, box.x1),
      y0: Math.min(box.y0, box.y1),
      x1: Math.max(box.x0, box.x1),
      y1: Math.max(box.y0, box.y1),
    };
  }

  function boxMetrics(mask, box) {
    const normalized = normalizedBox(box);
    if (!normalized) return { intersection: 0, insideRatio: 0, iou: 0 };
    const x0 = clamp(Math.floor(normalized.x0 * MASK_SCALE), 0, MASK_WIDTH - 1);
    const y0 = clamp(Math.floor(normalized.y0 * MASK_SCALE), 0, MASK_HEIGHT - 1);
    const x1 = clamp(Math.ceil(normalized.x1 * MASK_SCALE), 0, MASK_WIDTH - 1);
    const y1 = clamp(Math.ceil(normalized.y1 * MASK_SCALE), 0, MASK_HEIGHT - 1);
    let intersection = 0;
    let area = 0;
    for (let y = 0; y < MASK_HEIGHT; y += 1) {
      for (let x = 0; x < MASK_WIDTH; x += 1) {
        if (!mask[y * MASK_WIDTH + x]) continue;
        area += 1;
        if (x >= x0 && x <= x1 && y >= y0 && y <= y1) intersection += 1;
      }
    }
    const boxArea = Math.max(1, (x1 - x0 + 1) * (y1 - y0 + 1));
    const union = area + boxArea - intersection;
    return {
      intersection,
      insideRatio: area ? intersection / area : 0,
      iou: union ? intersection / union : 0,
    };
  }

  function maskFromCanvas(canvas) {
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const pixels = context.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    const mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let index = 0; index < mask.length; index += 1) {
      mask[index] = pixels[index * 4 + 3] > 0 ? 1 : 0;
    }
    return mask;
  }

  function rasterizePath(pathData) {
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.setTransform(MASK_SCALE, 0, 0, MASK_SCALE, 0, 0);
    context.fillStyle = "#fff";
    context.fill(new Path2D(pathData));
    return maskFromCanvas(canvas);
  }

  function rasterizePolygon(pointsText) {
    const points = String(pointsText || "")
      .trim()
      .split(/\s+/)
      .map((pair) => pair.split(",").map(Number))
      .filter((pair) => pair.length === 2 && pair.every(Number.isFinite));
    const canvas = document.createElement("canvas");
    canvas.width = MASK_WIDTH;
    canvas.height = MASK_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.setTransform(MASK_SCALE, 0, 0, MASK_SCALE, 0, 0);
    context.fillStyle = "#fff";
    context.beginPath();
    points.forEach((point, index) => {
      if (index === 0) context.moveTo(point[0], point[1]);
      else context.lineTo(point[0], point[1]);
    });
    context.closePath();
    context.fill();
    return maskFromCanvas(canvas);
  }

  function filledPathNodes(documentNode) {
    const nonFilledClasses = new Set();
    documentNode.querySelectorAll("style").forEach((style) => {
      const matches = style.textContent.matchAll(/\.([-\\w]+)\\s*\\{[^}]*\\bfill\\s*:\\s*none\\b[^}]*\}/gi);
      for (const match of matches) nonFilledClasses.add(match[1]);
    });
    return Array.from(documentNode.querySelectorAll("path[d]")).filter((node) => {
      const classes = String(node.getAttribute("class") || "").split(/\s+/);
      return !classes.some((className) => nonFilledClasses.has(className));
    });
  }

  class PromptDemo {
    constructor(root) {
      this.root = root;
      this.points = [];
      this.box = null;
      this.selected = null;
      this.drag = null;
      this.tool = "point_pos";
      this.candidates = [];
      this.activeCandidate = null;
      this.sourceImage = null;
      this.domainArea = 1;
      this.promptRegions = [];
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
      this.buildCandidates(documentNode);
      this.bindInteractions();
      this.setTool("point_pos");
      this.render();
      this.announce("Prompt demo ready. Add a positive point to begin.");
    }

    buildInterface() {
      const iconBase = new URL(this.root.dataset.iconBase, window.location.href);
      this.root.innerHTML = "";
      this.shell = document.createElement("div");
      this.shell.className = "swell-prompt-demo__shell";
      this.stage = document.createElement("div");
      this.stage.className = "swell-prompt-demo__stage";
      this.canvas = document.createElement("canvas");
      this.canvas.className = "swell-prompt-demo__canvas";
      this.canvas.width = VIEW_WIDTH;
      this.canvas.height = VIEW_HEIGHT;
      this.canvas.tabIndex = 0;
      this.canvas.setAttribute("aria-label", "Interactive simulated segmentation viewer");
      this.context = this.canvas.getContext("2d");
      this.rail = document.createElement("div");
      this.rail.className = "swell-prompt-demo__rail";
      this.rail.setAttribute("role", "toolbar");
      this.rail.setAttribute("aria-label", "Prompt tools");

      TOOL_DEFINITIONS.forEach((definition) => {
        const button = this.makeToolButton(definition, new URL(definition.icon, iconBase));
        this.buttons.set(definition.id, button);
        this.rail.appendChild(button);
      });

      const clearButton = this.makeToolButton(CLEAR_TOOL, new URL(CLEAR_TOOL.icon, iconBase));
      clearButton.classList.add("swell-prompt-demo__tool--clear");
      clearButton.removeAttribute("aria-pressed");
      this.rail.appendChild(clearButton);

      this.status = document.createElement("p");
      this.status.className = "swell-prompt-demo__sr-status";
      this.status.setAttribute("aria-live", "polite");
      this.toolHelp = document.createElement("p");
      this.toolHelp.className = "swell-prompt-demo__tool-help";
      this.toolHelp.setAttribute("aria-live", "polite");
      this.stage.append(this.canvas, this.rail, this.status);
      this.shell.appendChild(this.stage);
      this.shell.appendChild(this.toolHelp);
      this.root.appendChild(this.shell);
    }

    makeToolButton(definition, iconUrl) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "swell-prompt-demo__tool";
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
          this.clear();
          this.setToolHelp(definition);
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

    buildCandidates(documentNode) {
      const pathNodes = filledPathNodes(documentNode);
      const rawMasks = pathNodes.map((node) => rasterizePath(node.getAttribute("d")));
      if (!rawMasks.length) throw new Error("The slice SVG has no segmentable paths.");
      const polygonNode = documentNode.querySelector("polygon[points]");
      const probeMask = polygonNode
        ? rasterizePolygon(polygonNode.getAttribute("points"))
        : new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
      let domain = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
      rawMasks.forEach((mask) => { domain = combineMasks(domain, mask, "union"); });
      domain = combineMasks(domain, probeMask, "subtract");
      this.domainArea = Math.max(1, countMask(domain));
      this.promptRegions = rawMasks
        .map((mask) => combineMasks(mask, probeMask, "subtract"))
        .filter((mask) => countMask(mask) > 40);

      const visibleMasks = rawMasks.map((mask, regionIndex) => {
        let visible = combineMasks(mask, probeMask, "subtract");
        for (let later = regionIndex + 1; later < rawMasks.length; later += 1) {
          visible = combineMasks(visible, rawMasks[later], "subtract");
        }
        return visible;
      }).filter((mask) => countMask(mask) > 40);

      visibleMasks.forEach((exact, regionIndex) => {
        const under = morphMask(exact, false, 3);
        const over = combineMasks(morphMask(exact, true, 5), domain, "intersect");
        this.addCandidate(regionIndex, "under", under);
        this.addCandidate(regionIndex, "exact", exact);
        this.addCandidate(regionIndex, "over", over);

        const neighborhood = morphMask(exact, true, 8);
        let adjacentIndex = -1;
        let adjacentScore = 0;
        visibleMasks.forEach((other, otherIndex) => {
          if (otherIndex === regionIndex) return;
          const overlap = countMask(combineMasks(neighborhood, other, "intersect"));
          if (overlap > adjacentScore) {
            adjacentScore = overlap;
            adjacentIndex = otherIndex;
          }
        });
        if (adjacentIndex >= 0) {
          this.addCandidate(regionIndex, "adjacent", combineMasks(exact, visibleMasks[adjacentIndex], "union"));
        }
      });

      // Any anatomical regions can be selected together. A small SVG keeps
      // every possible exact combination tractable and makes multiple prompts
      // resolve predictably instead of eliminating all candidates.
      const subsetCount = 1 << visibleMasks.length;
      for (let subset = 1; subset < subsetCount; subset += 1) {
        if ((subset & (subset - 1)) === 0) continue;
        let combined = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
        let firstRegion = 0;
        for (let regionIndex = 0; regionIndex < visibleMasks.length; regionIndex += 1) {
          if (!(subset & (1 << regionIndex))) continue;
          combined = combineMasks(combined, visibleMasks[regionIndex], "union");
          firstRegion = regionIndex;
        }
        this.addCandidate(firstRegion, "combined", combined);
      }
    }

    addCandidate(regionIndex, variant, mask) {
      const area = countMask(mask);
      if (!area) return;
      this.candidates.push({
        area,
        bounds: maskBounds(mask),
        mask,
        regionIndex,
        variant,
      });
    }

    bindInteractions() {
      this.canvas.addEventListener("pointerdown", (event) => this.onPointerDown(event));
      this.canvas.addEventListener("pointermove", (event) => this.onPointerMove(event));
      this.canvas.addEventListener("pointerup", (event) => this.onPointerUp(event));
      this.canvas.addEventListener("pointercancel", (event) => this.onPointerUp(event));
      this.canvas.addEventListener("keydown", (event) => this.onKeyDown(event));
    }

    setTool(tool) {
      this.tool = tool;
      this.selected = null;
      this.buttons.forEach((button, id) => {
        button.setAttribute("aria-pressed", id === tool ? "true" : "false");
      });
      this.setToolHelp(TOOL_DEFINITIONS.find((definition) => definition.id === tool));
      this.syncCursor();
      this.render();
    }

    syncCursor() {
      this.canvas.style.cursor = this.tool === "select" ? "default" : "crosshair";
    }

    setToolHelp(definition) {
      if (this.toolHelp && definition) this.toolHelp.textContent = definition.description;
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
      this.canvas.setPointerCapture(event.pointerId);
      if (this.tool === "point_pos" || this.tool === "point_neg") {
        this.points.push({ x: point.x, y: point.y, label: this.tool === "point_pos" ? 1 : 0 });
        this.selected = { type: "point", index: this.points.length - 1 };
        this.recompute();
        return;
      }
      if (this.tool === "box") {
        this.box = { x0: point.x, y0: point.y, x1: point.x, y1: point.y };
        this.selected = { type: "box", handle: "se" };
        this.drag = { type: "new_box" };
        this.render();
        return;
      }
      this.beginSelectionDrag(point);
    }

    beginSelectionDrag(point) {
      for (let index = this.points.length - 1; index >= 0; index -= 1) {
        const candidate = this.points[index];
        if (Math.hypot(candidate.x - point.x, candidate.y - point.y) <= 12) {
          this.selected = { type: "point", index };
          this.drag = { type: "point", index };
          this.render();
          return;
        }
      }
      const box = normalizedBox(this.box);
      if (box) {
        const handles = {
          nw: { x: box.x0, y: box.y0 }, ne: { x: box.x1, y: box.y0 },
          sw: { x: box.x0, y: box.y1 }, se: { x: box.x1, y: box.y1 },
        };
        for (const [handle, coordinate] of Object.entries(handles)) {
          if (Math.hypot(coordinate.x - point.x, coordinate.y - point.y) <= 14) {
            this.selected = { type: "box", handle };
            this.drag = { type: "box_handle", handle };
            this.box = { ...box };
            this.render();
            return;
          }
        }
        if (point.x >= box.x0 && point.x <= box.x1 && point.y >= box.y0 && point.y <= box.y1) {
          this.selected = { type: "box", handle: null };
          this.drag = { type: "box_move", start: point, original: { ...box } };
          this.box = { ...box };
          this.render();
          return;
        }
      }
      this.selected = null;
      this.drag = null;
      this.render();
    }

    onPointerMove(event) {
      if (!this.drag) return;
      event.preventDefault();
      const point = this.pointFromEvent(event);
      if (this.drag.type === "point") {
        const selectedPoint = this.points[this.drag.index];
        selectedPoint.x = point.x;
        selectedPoint.y = point.y;
      } else if (this.drag.type === "new_box") {
        this.box.x1 = point.x;
        this.box.y1 = point.y;
      } else if (this.drag.type === "box_handle") {
        const box = normalizedBox(this.box);
        if (this.drag.handle.includes("n")) box.y0 = point.y;
        if (this.drag.handle.includes("s")) box.y1 = point.y;
        if (this.drag.handle.includes("w")) box.x0 = point.x;
        if (this.drag.handle.includes("e")) box.x1 = point.x;
        this.box = box;
      } else if (this.drag.type === "box_move") {
        const dx = point.x - this.drag.start.x;
        const dy = point.y - this.drag.start.y;
        const width = this.drag.original.x1 - this.drag.original.x0;
        const height = this.drag.original.y1 - this.drag.original.y0;
        const x0 = clamp(this.drag.original.x0 + dx, 0, VIEW_WIDTH - width);
        const y0 = clamp(this.drag.original.y0 + dy, 0, VIEW_HEIGHT - height);
        this.box = { x0, y0, x1: x0 + width, y1: y0 + height };
      }
      this.recompute(false);
    }

    onPointerUp(event) {
      if (!this.drag) return;
      event.preventDefault();
      if (this.box) {
        this.box = normalizedBox(this.box);
        if (this.box.x1 - this.box.x0 < 5 || this.box.y1 - this.box.y0 < 5) this.box = null;
      }
      this.drag = null;
      this.recompute();
    }

    onKeyDown(event) {
      const key = event.key;
      if (key === "v" || key === "V") this.setTool("select");
      else if (key === "+" || key === "=") this.setTool("point_pos");
      else if (key === "-") this.setTool("point_neg");
      else if (key === "k" || key === "K") this.setTool("box");
      else if (key === "Delete" || key === "Backspace") this.deleteSelected();
      else return;
      event.preventDefault();
    }

    deleteSelected() {
      if (!this.selected) return;
      if (this.selected.type === "point") this.points.splice(this.selected.index, 1);
      if (this.selected.type === "box") this.box = null;
      this.selected = null;
      this.drag = null;
      this.recompute();
    }

    clear() {
      this.points = [];
      this.box = null;
      this.selected = null;
      this.drag = null;
      this.activeCandidate = null;
      this.announce("All prompts and the simulated mask were cleared.");
      this.render();
    }

    recompute(announce = true) {
      this.activeCandidate = this.chooseCandidate();
      if (announce) {
        this.announce(this.activeCandidate
          ? `Simulated ${this.activeCandidate.variant} mask preview.`
          : "No simulated mask matches the current prompts.");
      }
      this.render();
    }

    chooseCandidate() {
      const positives = this.points.filter((point) => point.label === 1);
      const negatives = this.points.filter((point) => point.label === 0);
      if (!positives.length && !this.box) return null;
      const ambiguous = positives.length === 1 && negatives.length === 0 && !this.box;
      let best = null;
      let bestScore = -Infinity;
      this.candidates.forEach((candidate, stableIndex) => {
        if (positives.some((point) => !maskContains(candidate.mask, point))) return;
        let score = 0;
        positives.forEach(() => { score += 120; });
        negatives.forEach((point) => {
          score += maskContains(candidate.mask, point) ? -190 : 8;
        });
        if (this.box) {
          const metrics = boxMetrics(candidate.mask, this.box);
          if (!metrics.intersection) return;
          score += metrics.iou * 120 + metrics.insideRatio * 90;
          score -= (1 - metrics.insideRatio) * 100;
        }
        if (ambiguous) {
          const preferred = candidate.regionIndex % 2 === 0 ? "over" : "under";
          score += candidate.variant === preferred ? 30 : 0;
          score += candidate.variant === "adjacent" ? 16 : 0;
          score += candidate.variant === "exact" ? 8 : 0;
        } else {
          score += candidate.variant === "exact" ? 24 : 0;
          score += candidate.variant === "under" || candidate.variant === "over" ? 8 : 0;
        }
        score -= candidate.area / this.domainArea * 4;
        score -= stableIndex * 0.0001;
        if (score > bestScore) {
          best = candidate;
          bestScore = score;
        }
      });
      return best || this.fallbackCandidateFor(positives, negatives);
    }

    fallbackCandidateFor(positives, negatives) {
      if (!positives.length) return null;
      let combined = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
      for (const point of positives) {
        const matches = this.promptRegions.filter((mask) => maskContains(mask, point));
        if (!matches.length) return null;
        const smallestMatch = matches.reduce((smallest, mask) => (
          countMask(mask) < countMask(smallest) ? mask : smallest
        ));
        combined = combineMasks(combined, smallestMatch, "union");
      }
      if (negatives.some((point) => maskContains(combined, point))) return null;
      return {
        area: countMask(combined),
        bounds: maskBounds(combined),
        mask: combined,
        regionIndex: -1,
        variant: "combined",
      };
    }

    announce(message) {
      if (this.status) this.status.textContent = message;
    }

    render() {
      if (!this.context) return;
      this.context.clearRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.fillStyle = "#0f1318";
      this.context.fillRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      if (this.sourceImage) this.context.drawImage(this.sourceImage, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      if (this.activeCandidate) this.drawMask(this.activeCandidate.mask);
      this.drawBox();
      this.drawPoints();
    }

    drawMask(mask) {
      const canvas = document.createElement("canvas");
      canvas.width = MASK_WIDTH;
      canvas.height = MASK_HEIGHT;
      const context = canvas.getContext("2d");
      const image = context.createImageData(MASK_WIDTH, MASK_HEIGHT);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          const maskIndex = y * MASK_WIDTH + x;
          if (!mask[maskIndex]) continue;
          const boundary = x === 0 || y === 0 || x === MASK_WIDTH - 1 || y === MASK_HEIGHT - 1
            || !mask[maskIndex - 1] || !mask[maskIndex + 1]
            || !mask[maskIndex - MASK_WIDTH] || !mask[maskIndex + MASK_WIDTH];
          const pixelIndex = maskIndex * 4;
          image.data[pixelIndex] = MASK_BLUE[0];
          image.data[pixelIndex + 1] = MASK_BLUE[1];
          image.data[pixelIndex + 2] = MASK_BLUE[2];
          image.data[pixelIndex + 3] = boundary ? 235 : 92;
        }
      }
      context.putImageData(image, 0, 0);
      this.context.save();
      this.context.imageSmoothingEnabled = false;
      this.context.drawImage(canvas, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.restore();
    }

    drawPoints() {
      this.points.forEach((point, index) => {
        const selected = this.selected && this.selected.type === "point" && this.selected.index === index;
        this.context.beginPath();
        this.context.arc(point.x, point.y, selected ? 7 : 5, 0, Math.PI * 2);
        this.context.fillStyle = point.label === 1 ? "#38a169" : "#e05252";
        this.context.fill();
        this.context.lineWidth = selected ? 3 : 2;
        this.context.strokeStyle = selected ? "#f5c451" : "#ffffff";
        this.context.stroke();
      });
    }

    drawBox() {
      const box = normalizedBox(this.box);
      if (!box) return;
      const selected = this.selected && this.selected.type === "box";
      this.context.save();
      this.context.strokeStyle = selected ? "#f5c451" : "#ffffff";
      this.context.lineWidth = 2;
      this.context.setLineDash([7, 5]);
      this.context.strokeRect(box.x0, box.y0, box.x1 - box.x0, box.y1 - box.y0);
      this.context.setLineDash([]);
      if (selected) {
        this.context.fillStyle = "#f5c451";
        [[box.x0, box.y0], [box.x1, box.y0], [box.x0, box.y1], [box.x1, box.y1]].forEach(([x, y]) => {
          this.context.fillRect(x - 4, y - 4, 8, 8);
        });
      }
      this.context.restore();
    }
  }

  function mountPromptDemos() {
    document.querySelectorAll("[data-swell-prompt-demo]").forEach((root) => {
      if (root.dataset.swellPromptMounted === "true") return;
      root.dataset.swellPromptMounted = "true";
      const demo = new PromptDemo(root);
      root.swellPromptDemo = demo;
      demo.initialize().catch((error) => {
        root.innerHTML = `<p class="swell-prompt-demo__fallback">Prompt demo unavailable: ${error.message}</p>`;
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountPromptDemos, { once: true });
  } else {
    mountPromptDemos();
  }
  if (typeof document$ !== "undefined") document$.subscribe(mountPromptDemos);
}());
