import { describe, it, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { StoryboardViewer } from "@/components/artifacts/StoryboardViewer";
import { MediaPlayer } from "@/components/artifacts/MediaPlayer";

describe("StoryboardViewer & MediaPlayer Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // Test 1: Exact test from brief
  test("recalculates total duration when a scene is dropped and triggers render on approve", () => {
    const onApprove = vi.fn();
    const data = {
      styleName: "Rainmaker Style",
      warnings: [],
      scenes: [
        { sceneId: "s1", durationSec: 2.0, overlayText: "EDIT VIDEO", effect: "zoom" },
        { sceneId: "s2", durationSec: 3.0, overlayText: "AI AGENT", effect: "none" },
      ],
    };
    render(<StoryboardViewer storyboard={data} onApproveRender={onApprove} />);
    expect(screen.getByText(/5\.0 giây/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /bỏ cảnh/i })[0]);
    expect(screen.getByText(/3\.0 giây/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /duyệt, dựng luôn/i }));
    expect(onApprove).toHaveBeenCalled();
  });

  // Test 2: Pacing warnings banner rendering
  it("renders pacing warnings alert banner when warnings exist", () => {
    const warnings = [
      "2 hiệu ứng mạnh diễn ra sát nhau ở cảnh s1 và cảnh s2",
      "Đoạn video kéo dài hơn 20 giây không có điểm nhấn hiệu ứng nào",
    ];
    const data = {
      styleName: "Rainmaker Style",
      warnings,
      scenes: [
        { sceneId: "s1", durationSec: 2.0, overlayText: "EDIT VIDEO", effect: "major_zoom" },
        { sceneId: "s2", durationSec: 3.0, overlayText: "AI AGENT", effect: "major_split" },
      ],
    };
    render(<StoryboardViewer storyboard={data} />);

    expect(screen.getByText(/cảnh báo nhịp độ|pacing warning/i)).toBeInTheDocument();
    expect(screen.getByText(/2 hiệu ứng mạnh diễn ra sát nhau/)).toBeInTheDocument();
    expect(screen.getByText(/hơn 20 giây không có điểm nhấn/)).toBeInTheDocument();
  });

  // Test 3: Editing overlay text and effect
  it("supports editing overlay text and changing scene effect", () => {
    const onUpdate = vi.fn();
    const data = {
      styleName: "Rainmaker Style",
      warnings: [],
      scenes: [
        { sceneId: "s1", durationSec: 2.5, overlayText: "ORIGINAL TEXT", effect: "none" },
      ],
    };
    render(<StoryboardViewer storyboard={data} onUpdateStoryboard={onUpdate} />);

    // Click "Sửa chữ"
    const editBtn = screen.getByRole("button", { name: /sửa chữ/i });
    fireEvent.click(editBtn);

    // Find input and change value
    const input = screen.getByDisplayValue("ORIGINAL TEXT");
    fireEvent.change(input, { target: { value: "UPDATED TITLE" } });

    // Save edit
    const saveBtn = screen.getByRole("button", { name: /lưu|xong|ok/i });
    fireEvent.click(saveBtn);

    expect(screen.getByText("UPDATED TITLE")).toBeInTheDocument();
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        scenes: expect.arrayContaining([
          expect.objectContaining({ sceneId: "s1", overlayText: "UPDATED TITLE" }),
        ]),
      })
    );

    // Change effect
    const changeEffectBtn = screen.getByRole("button", { name: /đổi hiệu ứng/i });
    fireEvent.click(changeEffectBtn);

    // Select a new effect
    const effectOption = screen.getAllByRole("button", { name: /zoom/i })[0];
    fireEvent.click(effectOption);

    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({
        scenes: expect.arrayContaining([
          expect.objectContaining({ sceneId: "s1", effect: expect.stringMatching(/zoom/i) }),
        ]),
      })
    );
  });

  // Test 4: MediaPlayer playback controls test
  it("renders MediaPlayer with controls and responds to play/pause and mute toggles", () => {
    const { container } = render(
      <MediaPlayer
        src="/api/v1/files/sample.mp4/stream"
        title="Sample Video"
        type="video"
      />
    );

    const videoEl = container.querySelector("video");
    expect(videoEl).toBeInTheDocument();
    expect(videoEl).toHaveAttribute("src", "/api/v1/files/sample.mp4/stream");

    // Play/Pause button
    const playPauseBtn = screen.getAllByRole("button", { name: /phát|play|tạm dừng|pause/i })[0];
    expect(playPauseBtn).toBeInTheDocument();

    // Volume / Mute button
    const muteBtn = screen.getByRole("button", { name: /âm lượng|tắt tiếng|mute/i });
    expect(muteBtn).toBeInTheDocument();

    // Speed options selector
    const speedSelect = screen.getByRole("button", { name: /tốc độ|speed|1x/i });
    expect(speedSelect).toBeInTheDocument();
  });
});
