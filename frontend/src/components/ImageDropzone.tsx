import React, { useState, useCallback, useRef } from 'react';

interface ImageDropzoneProps {
  onFileSelect: (file: File) => void;
  onFileRemove: () => void;
  previewUrl: string | null;
}

export default function ImageDropzone({ onFileSelect, onFileRemove, previewUrl }: ImageDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault(); // This is necessary to allow dropping
    e.stopPropagation();
  };

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileSelect(e.dataTransfer.files[0]);
      e.dataTransfer.clearData();
    }
  }, [onFileSelect]);

  const onButtonClick = () => {
    fileInputRef.current?.click();
  };
  
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      onFileSelect(e.target.files[0]);
    }
  };

  const containerClasses = `
    border-2 border-dashed rounded-lg p-6 text-center cursor-pointer
    transition-colors duration-200 ease-in-out
    ${isDragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}
  `;

  return (
    <div
      className={containerClasses}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      onClick={onButtonClick}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png, image/jpeg, image/webp"
        className="hidden"
        onChange={handleFileChange}
      />
      {previewUrl ? (
        <div className="relative">
          <img src={previewUrl} alt="Character preview" className="mx-auto max-h-40 rounded-md" />
          <button
            onClick={(e) => {
              e.stopPropagation(); // Prevent triggering the file input click
              onFileRemove();
            }}
            className="absolute top-0 right-0 -mt-2 -mr-2 bg-red-500 text-white rounded-full h-6 w-6 flex items-center justify-center font-bold"
            aria-label="Remove image"
          >
            &times;
          </button>
        </div>
      ) : (
        <div>
          <p className="text-gray-500">Drag & drop an image here</p>
          <p className="text-gray-400 text-sm">or click to select a file</p>
        </div>
      )}
    </div>
  );
}