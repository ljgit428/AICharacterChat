"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, Video, X } from "lucide-react";

/**
 * 实时模式的摄像头 PiP 面板：可拖拽预览 + 手动快门。
 *
 * 帧的自动附带由父组件在发送时刻通过 registerFrameGrabber 注册的
 * grabFrame() 拉取（≥5s 限频），本组件只负责采集与展示。
 */

interface CameraPanelProps {
  /** camera = 摄像头；screen = 屏幕共享（getDisplayMedia），供角色"看屏幕"。 */
  mode?: "camera" | "screen";
  onClose: () => void;
  onSnapshot?: (file: File) => void;
  registerFrameGrabber: (grab: (() => File | null) | null) => void;
  snapshotLabel: string;
  closeLabel: string;
  deniedLabel: string;
}

export default function CameraPanel({
  mode = "camera",
  onClose,
  onSnapshot,
  registerFrameGrabber,
  snapshotLabel,
  closeLabel,
  deniedLabel,
}: CameraPanelProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [denied, setDenied] = useState(false);
  const [position, setPosition] = useState({ right: 24, bottom: 120 });
  const dragRef = useRef<{ startX: number; startY: number; startRight: number; startBottom: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const stream =
          mode === "screen"
            ? await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
            : await navigator.mediaDevices.getUserMedia({
                video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
                audio: false,
              });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        // 屏幕共享被用户从浏览器栏手动停止时，同步关闭面板。
        stream.getVideoTracks()[0]?.addEventListener("ended", onClose);
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
        }
      } catch (error) {
        console.error(`${mode} capture failed:`, error);
        if (!cancelled) setDenied(true);
      }
    })();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      registerFrameGrabber(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  const grabFrame = useCallback((): File | null => {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0) return null;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) return null;
    context.drawImage(video, 0, 0);
    const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
    const binary = atob(dataUrl.split(",")[1] || "");
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    return new File([bytes], `camera-${Date.now()}.jpg`, { type: "image/jpeg" });
  }, []);

  useEffect(() => {
    if (denied) return;
    registerFrameGrabber(grabFrame);
    return () => registerFrameGrabber(null);
  }, [denied, grabFrame, registerFrameGrabber]);

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest("button")) return;
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startRight: position.right,
      startBottom: position.bottom,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    setPosition({
      right: Math.max(8, drag.startRight - (event.clientX - drag.startX)),
      bottom: Math.max(8, drag.startBottom - (event.clientY - drag.startY)),
    });
  };

  const handlePointerUp = () => {
    dragRef.current = null;
  };

  return (
    <div
      className="fixed z-30 w-48 overflow-hidden rounded-[1.25rem] border border-white/70 bg-slate-900/85 shadow-[0_20px_60px_rgba(15,23,42,0.25)] backdrop-blur"
      style={{ right: position.right, bottom: position.bottom }}
    >
      <div
        className="flex cursor-grab items-center justify-between gap-2 px-3 py-2 active:cursor-grabbing"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
      >
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.14em] text-white/70">
          <Video size={12} />
        </span>
        <div className="flex items-center gap-1">
          {onSnapshot && !denied && (
            <button
              type="button"
              onClick={() => {
                const file = grabFrame();
                if (file) onSnapshot(file);
              }}
              className="rounded-lg p-1 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
              title={snapshotLabel}
            >
              <Camera size={13} />
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-white/70 transition-colors hover:bg-white/10 hover:text-white"
            title={closeLabel}
          >
            <X size={13} />
          </button>
        </div>
      </div>
      {denied ? (
        <p className="px-3 pb-3 text-xs leading-5 text-white/70">{deniedLabel}</p>
      ) : (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={`block h-36 w-full bg-black object-cover ${mode === "camera" ? "scale-x-[-1]" : ""}`}
        />
      )}
    </div>
  );
}
