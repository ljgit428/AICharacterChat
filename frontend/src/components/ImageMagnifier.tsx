// frontend/src/components/ImageMagnifier.tsx

"use client";

import React, { useState } from 'react';
import Image from 'next/image';

// 从 'next/image' 的 props 类型中继承，同时移除我们不需要的 'src' 和 'alt'
type ImageMagnifierProps = Omit<React.ComponentProps<typeof Image>, 'src' | 'alt'> & {
  src: string;
  alt: string;
};

const ImageMagnifier: React.FC<ImageMagnifierProps> = ({ src, alt, width, height, className, ...props }) => {
  const [isMagnified, setIsMagnified] = useState(false);

  const handleToggleMagnify = () => {
    setIsMagnified(!isMagnified);
  };

  // --- ▼▼▼ 核心修正：判断是否为 Blob URL ▼▼▼ ---
  const isBlobUrl = src && src.startsWith('blob:');
  // --- ▲▲▲ 修正结束 ▲▲▲ ---

  return (
    <>
      <div className="cursor-zoom-in" onClick={handleToggleMagnify}>
        {/*
          如果 src 是 blob URL，我们必须使用标准的 <img> 标签。
          否则，我们使用经过优化的 next/image 组件。
        */}
        {isBlobUrl ? (
          <img
            src={src}
            alt={alt}
            width={Number(width)}
            height={Number(height)}
            className={className}
          />
        ) : (
          <Image
            src={src}
            alt={alt}
            width={width}
            height={height}
            className={className}
            {...props}
          />
        )}
      </div>

      {isMagnified && (
        <div
          className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-4"
          onClick={handleToggleMagnify}
        >
          {/* 使用标准的 <img> 标签来显示放大后的图片，因为它能最好地自适应屏幕大小 */}
          <img
            src={src}
            alt={alt}
            className="max-w-full max-h-full object-contain"
          />
        </div>
      )}
    </>
  );
};

export default ImageMagnifier;