(function () {
  "use strict";

  const VIEW_WIDTH = 792;
  const VIEW_HEIGHT = 612;
  const MASK_WIDTH = 396;
  const MASK_HEIGHT = 306;
  const MASK_SCALE = MASK_WIDTH / VIEW_WIDTH;
  const MASK_BLUE = [27, 117, 188];

  const TOOLS = [
    {
      id: "brush",
      label: "Brush + (B)",
      icon: "Brush Icon@4x.png",
      description: "Paint directly onto the mask. Use the brush-size control to change the stroke radius.",
    },
    {
      id: "eraser",
      label: "Brush - (E)",
      icon: "Eraser Icon@4x.png",
      description: "Erase directly from the mask. It uses the same brush size as Brush +.",
    },
    {
      id: "fill",
      label: "Fill + (G)",
      icon: "Fill+ Icon@4x.png",
      description: "Add a connected tissue region to the mask with one click.",
    },
    {
      id: "fill_erase",
      label: "Fill - (Shift+G)",
      icon: "FIll- Icon@4x.png",
      description: "Remove the connected mask component under the cursor with one click.",
    },
  ];

  const CLEAR_TOOL = {
    id: "clear",
    label: "Clear Frame",
    icon: "Clear Frame Icon@4x.png",
    description: "Remove the mask and every direct edit from this frame.",
  };

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
    }
    return output;
  }

  function morphMask(source, iterations) {
    let current = new Uint8Array(source);
    for (let iteration = 0; iteration < iterations; iteration += 1) {
      const next = new Uint8Array(current.length);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          let keep = 1;
          for (let dy = -1; dy <= 1; dy += 1) {
            for (let dx = -1; dx <= 1; dx += 1) {
              const nx = x + dx;
              const ny = y + dy;
              if (nx < 0 || nx >= MASK_WIDTH || ny < 0 || ny >= MASK_HEIGHT || !current[ny * MASK_WIDTH + nx]) {
                keep = 0;
              }
            }
          }
          next[y * MASK_WIDTH + x] = keep;
        }
      }
      current = next;
    }
    return current;
  }

  function maskFromCanvas(canvas) {
    const context = canvas.getContext("2d", { willReadFrequently: true });
    const pixels = context.getImageData(0, 0, MASK_WIDTH, MASK_HEIGHT).data;
    const mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
    for (let index = 0; index < mask.length; index += 1) mask[index] = pixels[index * 4 + 3] > 0 ? 1 : 0;
    return mask;
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

  function maskContains(mask, point) {
    const x = clamp(Math.floor(point.x * MASK_SCALE), 0, MASK_WIDTH - 1);
    const y = clamp(Math.floor(point.y * MASK_SCALE), 0, MASK_HEIGHT - 1);
    return Boolean(mask[y * MASK_WIDTH + x]);
  }

  class MaskEditDemo {
    constructor(root) {
      this.root = root;
      this.tool = "brush";
      this.brushSize = 10;
      this.mask = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
      this.fillRegions = [];
      this.dragging = false;
      this.lastPoint = null;
      this.hoverPoint = null;
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
      this.prepareMasks(documentNode);
      this.bindInteractions();
      this.setTool("brush");
      this.render();
      this.announce("Manual mask-editing demo ready. The initial mask is intentionally incomplete.");
    }

    buildInterface() {
      const iconBase = new URL(this.root.dataset.iconBase, window.location.href);
      this.root.innerHTML = "";
      this.shell = document.createElement("div");
      this.shell.className = "swell-mask-edit-demo__shell";
      this.stage = document.createElement("div");
      this.stage.className = "swell-mask-edit-demo__stage";
      this.canvas = document.createElement("canvas");
      this.canvas.className = "swell-mask-edit-demo__canvas";
      this.canvas.width = VIEW_WIDTH;
      this.canvas.height = VIEW_HEIGHT;
      this.canvas.tabIndex = 0;
      this.canvas.setAttribute("aria-label", "Interactive manual mask-editing viewer");
      this.context = this.canvas.getContext("2d");
      this.rail = document.createElement("div");
      this.rail.className = "swell-mask-edit-demo__rail";
      this.rail.setAttribute("role", "toolbar");
      this.rail.setAttribute("aria-label", "Manual mask-editing tools");
      TOOLS.forEach((definition) => {
        const button = this.makeToolButton(definition, new URL(definition.icon, iconBase));
        this.buttons.set(definition.id, button);
        this.rail.appendChild(button);
      });
      const clearButton = this.makeToolButton(CLEAR_TOOL, new URL(CLEAR_TOOL.icon, iconBase));
      clearButton.classList.add("swell-mask-edit-demo__tool--clear");
      clearButton.removeAttribute("aria-pressed");
      this.rail.appendChild(clearButton);
      this.status = document.createElement("p");
      this.status.className = "swell-mask-edit-demo__sr-status";
      this.status.setAttribute("aria-live", "polite");
      this.toolHelp = document.createElement("p");
      this.toolHelp.className = "swell-mask-edit-demo__tool-help";
      this.toolHelp.setAttribute("aria-live", "polite");
      this.options = document.createElement("div");
      this.options.className = "swell-mask-edit-demo__options";
      const brushLabel = document.createElement("label");
      brushLabel.textContent = "Brush size";
      brushLabel.htmlFor = "swell-mask-edit-demo-brush-size";
      this.sizeValue = document.createElement("output");
      this.sizeValue.textContent = "10 px";
      this.sizeInput = document.createElement("input");
      this.sizeInput.id = "swell-mask-edit-demo-brush-size";
      this.sizeInput.type = "range";
      this.sizeInput.min = "1";
      this.sizeInput.max = "50";
      this.sizeInput.value = "10";
      this.sizeInput.setAttribute("aria-label", "Brush size");
      this.sizeInput.addEventListener("input", () => {
        this.brushSize = Number(this.sizeInput.value);
        this.sizeValue.textContent = `${this.brushSize} px`;
        this.render();
      });
      this.options.append(brushLabel, this.sizeInput, this.sizeValue);
      this.stage.append(this.canvas, this.rail, this.status);
      this.shell.append(this.stage, this.options, this.toolHelp);
      this.root.appendChild(this.shell);
    }

    makeToolButton(definition, iconUrl) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "swell-mask-edit-demo__tool";
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
          this.mask.fill(0);
          this.announce("The mask and direct edits were cleared.");
          this.setToolHelp(definition);
          this.render();
        } else {
          this.setTool(definition.id);
        }
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

    prepareMasks(documentNode) {
      const pathNodes = filledPathNodes(documentNode);
      const rawMasks = pathNodes.map((node) => rasterizePath(node.getAttribute("d")));
      if (!rawMasks.length) throw new Error("The slice SVG has no editable paths.");
      const polygon = documentNode.querySelector("polygon[points]");
      const probeMask = polygon ? rasterizePolygon(polygon.getAttribute("points")) : new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
      const visibleMasks = rawMasks.map((mask, regionIndex) => {
        let visible = combineMasks(mask, probeMask, "subtract");
        for (let later = regionIndex + 1; later < rawMasks.length; later += 1) {
          visible = combineMasks(visible, rawMasks[later], "subtract");
        }
        return visible;
      });
      this.fillRegions = visibleMasks.filter((mask) => countMask(mask) > 40);
      const sdTargetIndex = pathNodes.findIndex((node) => node.getAttribute("class") === "cls-5");
      if (sdTargetIndex === -1) throw new Error("The slice SVG is missing the SD target region.");
      const sdTarget = visibleMasks[sdTargetIndex];
      this.mask = morphMask(sdTarget, 5);
    }

    bindInteractions() {
      this.canvas.addEventListener("pointerdown", (event) => this.onPointerDown(event));
      this.canvas.addEventListener("pointermove", (event) => this.onPointerMove(event));
      this.canvas.addEventListener("pointerup", () => this.endStroke());
      this.canvas.addEventListener("pointercancel", () => this.endStroke());
      this.canvas.addEventListener("pointerleave", () => this.onPointerLeave());
      this.canvas.addEventListener("keydown", (event) => this.onKeyDown(event));
    }

    pointFromEvent(event) {
      const rect = this.canvas.getBoundingClientRect();
      return {
        x: clamp((event.clientX - rect.left) * VIEW_WIDTH / rect.width, 0, VIEW_WIDTH),
        y: clamp((event.clientY - rect.top) * VIEW_HEIGHT / rect.height, 0, VIEW_HEIGHT),
      };
    }

    setTool(tool) {
      this.tool = tool;
      this.buttons.forEach((button, id) => button.setAttribute("aria-pressed", id === tool ? "true" : "false"));
      this.setToolHelp(TOOLS.find((definition) => definition.id === tool));
      this.syncCursor();
      this.render();
    }

    syncCursor() {
      this.canvas.style.cursor = this.tool === "brush" || this.tool === "eraser" ? "none" : "crosshair";
    }

    setToolHelp(definition) {
      if (definition) this.toolHelp.textContent = definition.description;
    }

    onPointerDown(event) {
      event.preventDefault();
      this.canvas.focus();
      const point = this.pointFromEvent(event);
      this.hoverPoint = point;
      if (this.tool === "fill" || this.tool === "fill_erase") {
        this.applyFill(point, this.tool === "fill" ? "add" : "remove");
        return;
      }
      this.dragging = true;
      this.lastPoint = point;
      this.canvas.setPointerCapture(event.pointerId);
      this.paintDisc(point, this.tool === "brush");
      this.render();
    }

    onPointerMove(event) {
      const point = this.pointFromEvent(event);
      if (this.tool === "brush" || this.tool === "eraser") this.hoverPoint = point;
      if (!this.dragging) {
        if (this.tool === "brush" || this.tool === "eraser") this.render();
        return;
      }
      event.preventDefault();
      this.paintLine(this.lastPoint, point, this.tool === "brush");
      this.lastPoint = point;
      this.render();
    }

    onPointerLeave() {
      this.hoverPoint = null;
      this.render();
    }

    endStroke() {
      if (!this.dragging) return;
      this.dragging = false;
      this.lastPoint = null;
      this.announce(this.tool === "brush" ? "Mask painted." : "Mask erased.");
    }

    onKeyDown(event) {
      if (event.key === "b" || event.key === "B") this.setTool("brush");
      else if (event.key === "e" || event.key === "E") this.setTool("eraser");
      else if (event.key === "g") this.setTool("fill");
      else if (event.key === "G") this.setTool("fill_erase");
      else return;
      event.preventDefault();
    }

    paintLine(from, to, add) {
      const radius = Math.max(1, this.brushSize * MASK_SCALE);
      const steps = Math.max(1, Math.ceil(Math.hypot(to.x - from.x, to.y - from.y) / Math.max(1, radius)));
      for (let step = 0; step <= steps; step += 1) {
        const t = step / steps;
        this.paintDisc({ x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t }, add);
      }
    }

    paintDisc(point, add) {
      const radius = Math.max(1, this.brushSize * MASK_SCALE);
      const centerX = Math.floor(point.x * MASK_SCALE);
      const centerY = Math.floor(point.y * MASK_SCALE);
      const radiusSquared = radius * radius;
      for (let y = Math.max(0, Math.floor(centerY - radius)); y <= Math.min(MASK_HEIGHT - 1, Math.ceil(centerY + radius)); y += 1) {
        for (let x = Math.max(0, Math.floor(centerX - radius)); x <= Math.min(MASK_WIDTH - 1, Math.ceil(centerX + radius)); x += 1) {
          if ((x - centerX) ** 2 + (y - centerY) ** 2 <= radiusSquared) this.mask[y * MASK_WIDTH + x] = add ? 1 : 0;
        }
      }
    }

    applyFill(point, mode) {
      if (mode === "add") {
        const matches = this.fillRegions.filter((mask) => maskContains(mask, point));
        if (!matches.length) {
          this.announce("Fill + needs a tissue region inside the slice.");
          return;
        }
        const region = matches.reduce((smallest, mask) => countMask(mask) < countMask(smallest) ? mask : smallest);
        this.mask = combineMasks(this.mask, region, "union");
        this.announce("Connected tissue region added to the mask.");
      } else {
        const x = clamp(Math.floor(point.x * MASK_SCALE), 0, MASK_WIDTH - 1);
        const y = clamp(Math.floor(point.y * MASK_SCALE), 0, MASK_HEIGHT - 1);
        if (!this.mask[y * MASK_WIDTH + x]) {
          this.announce("Fill - needs an existing mask component.");
          return;
        }
        this.removeComponent(x, y);
        this.announce("Connected mask component removed.");
      }
      this.render();
    }

    removeComponent(seedX, seedY) {
      const queue = [[seedX, seedY]];
      const visited = new Uint8Array(this.mask.length);
      while (queue.length) {
        const [x, y] = queue.pop();
        const index = y * MASK_WIDTH + x;
        if (visited[index] || !this.mask[index]) continue;
        visited[index] = 1;
        this.mask[index] = 0;
        if (x > 0) queue.push([x - 1, y]);
        if (x < MASK_WIDTH - 1) queue.push([x + 1, y]);
        if (y > 0) queue.push([x, y - 1]);
        if (y < MASK_HEIGHT - 1) queue.push([x, y + 1]);
      }
    }

    announce(message) {
      if (this.status) this.status.textContent = message;
    }

    render() {
      this.context.clearRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.context.fillStyle = "#0f1318";
      this.context.fillRect(0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      if (this.sourceImage) this.context.drawImage(this.sourceImage, 0, 0, VIEW_WIDTH, VIEW_HEIGHT);
      this.drawMask();
      this.drawBrushCursor();
    }

    drawBrushCursor() {
      if (!this.hoverPoint || (this.tool !== "brush" && this.tool !== "eraser")) return;
      this.context.save();
      this.context.beginPath();
      this.context.arc(this.hoverPoint.x, this.hoverPoint.y, this.brushSize, 0, Math.PI * 2);
      this.context.lineWidth = 2;
      this.context.strokeStyle = this.tool === "brush" ? "#edf1f3" : "#d14343";
      this.context.stroke();
      this.context.restore();
    }

    drawMask() {
      const canvas = document.createElement("canvas");
      canvas.width = MASK_WIDTH;
      canvas.height = MASK_HEIGHT;
      const context = canvas.getContext("2d");
      const image = context.createImageData(MASK_WIDTH, MASK_HEIGHT);
      for (let y = 0; y < MASK_HEIGHT; y += 1) {
        for (let x = 0; x < MASK_WIDTH; x += 1) {
          const maskIndex = y * MASK_WIDTH + x;
          if (!this.mask[maskIndex]) continue;
          const boundary = x === 0 || y === 0 || x === MASK_WIDTH - 1 || y === MASK_HEIGHT - 1
            || !this.mask[maskIndex - 1] || !this.mask[maskIndex + 1]
            || !this.mask[maskIndex - MASK_WIDTH] || !this.mask[maskIndex + MASK_WIDTH];
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
  }

  function mountMaskEditDemos() {
    document.querySelectorAll("[data-swell-mask-edit-demo]").forEach((root) => {
      if (root.dataset.swellMaskEditMounted === "true") return;
      root.dataset.swellMaskEditMounted = "true";
      const demo = new MaskEditDemo(root);
      root.swellMaskEditDemo = demo;
      demo.initialize().catch((error) => {
        root.innerHTML = `<p class="swell-mask-edit-demo__fallback">Manual mask-editing demo unavailable: ${error.message}</p>`;
      });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mountMaskEditDemos, { once: true });
  else mountMaskEditDemos();
  if (typeof document$ !== "undefined") document$.subscribe(mountMaskEditDemos);
}());
