# 6. Running Mask Propagation

After placing point, box, or brush prompts on one or more anchor frames:

1. Click **Run Propagation** in the right dock panel.
2. The SAM-2 model propagates the mask from your anchor frames across all frames in the event range.
3. Propagation progress is displayed in real-time as a blue (`#1b75bc`) loading band on the timeline.
4. If you notice inaccuracies on other frames, pause or wait for propagation to complete, add correction prompts on those frames, and re-run propagation. The model will refine its predictions using the new anchor data.
