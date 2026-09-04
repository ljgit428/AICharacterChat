"use client";

import { useEffect, useState } from "react";
import type { LevelListener } from "@/hooks/useVoiceInput";

/**
 * Owl Meeting 式麦克风音量表：5 根竖条，随输入音量实时起落。
 * 独立订阅 useVoiceInput 的 level（20fps），不经过 ChatInterface 主 state。
 */

const BAR_COUNT = 5;
// 5 根条各自的点亮阈值：安静→只亮第 1 根，大声→全亮。
const BAR_THRESHOLDS = [0.015, 0.04, 0.08, 0.14, 0.22];

interface MicLevelMeterProps {
  subscribe: (listener: LevelListener) => () => void;
  active?: boolean;
  barClassName?: string;
  activeBarClassName?: string;
}

export default function MicLevelMeter({
  subscribe,
  active = true,
  barClassName = "bg-slate-300",
  activeBarClassName = "bg-rose-500",
}: MicLevelMeterProps) {
  const [litCount, setLitCount] = useState(0);

  useEffect(() => {
    if (!active) {
      setLitCount(0);
      return;
    }
    const unsubscribe = subscribe((level) => {
      let lit = 0;
      for (const threshold of BAR_THRESHOLDS) {
        if (level > threshold) lit += 1;
      }
      // 减少无意义重渲染：条数没变就不 set。
      setLitCount((prev) => (prev === lit ? prev : lit));
    });
    return unsubscribe;
  }, [subscribe, active]);

  return (
    <span className="flex h-4 items-end gap-[2px]" aria-hidden="true">
      {Array.from({ length: BAR_COUNT }, (_, index) => {
        const heights = [6, 9, 12, 15, 16];
        return (
          <span
            key={index}
            className={`w-[3px] rounded-full transition-[height,background-color] duration-75 ${
              index < litCount ? activeBarClassName : barClassName
            }`}
            style={{ height: heights[index] }}
          />
        );
      })}
    </span>
  );
}
