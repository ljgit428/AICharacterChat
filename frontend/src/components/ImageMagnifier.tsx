"use client";

import React, { useState } from 'react';
import Image from 'next/image';

interface ImageMagnifierProps {
  src: string;
  alt: string;
  width: number;
  height: number;
  className?: string;
}

const ImageMagnifier: React.FC<ImageMagnifierProps> = ({ src, alt, width, height, className }) => {
  const [isModalOpen, setIsModalOpen] = useState(false);

  const openModal = () => setIsModalOpen(true);
  const closeModal = () => setIsModalOpen(false);

  return (
    <>
      {/* 这是聊天或文件上传区域中可见的、较小的图片 */}
      <div
        className="relative cursor-zoom-in"
        onClick={openModal} // 将事件从 onMouseEnter 改为 onClick
      >
        <Image
          src={src}
          alt={alt}
          width={width}
          height={height}
          className={className}
          style={{ objectFit: 'contain' }}
        />
      </div>

      {/* 这是全屏显示的图片模态框 */}
      {isModalOpen && (
        <div
          // 背景遮罩层，点击它可以关闭模态框
          className="fixed inset-0 bg-black bg-opacity-80 flex items-center justify-center z-[100] cursor-zoom-out"
          onClick={closeModal}
        >
          {/* 右上角的关闭按钮，提供明确的关闭操作 */}
          <button
            className="absolute top-4 right-4 text-white text-5xl font-light leading-none"
            onClick={closeModal}
            aria-label="Close image view"
          >
            &times;
          </button>

          {/* 图片容器，防止点击图片本身时关闭模态框 */}
          <div
            className="relative max-w-[90vw] max-h-[90vh]"
            onClick={(e) => e.stopPropagation()} // 阻止事件冒泡到背景层
          >
            {/* 在浮层中使用原生img标签可以更好地自适应尺寸 */}
            <img
              src={src}
              alt={alt}
              className="max-w-full max-h-full object-contain"
            />
          </div>
        </div>
      )}
    </>
  );
};

export default ImageMagnifier;