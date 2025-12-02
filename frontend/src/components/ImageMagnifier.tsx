"use client";

import React, { useState } from 'react';
import Image from 'next/image';

type ImageMagnifierProps = Omit<React.ComponentProps<typeof Image>, 'src' | 'alt'> & {
  src: string;
  alt: string;
};

const ImageMagnifier: React.FC<ImageMagnifierProps> = ({ src, alt, width, height, className, ...props }) => {
  const [isMagnified, setIsMagnified] = useState(false);

  const handleToggleMagnify = () => {
    setIsMagnified(!isMagnified);
  };

    const isBlobUrl = src && src.startsWith('blob:');
  
  return (
    <>
      <div className="cursor-zoom-in" onClick={handleToggleMagnify}>
        
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