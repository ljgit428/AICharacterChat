import React, { useState, useCallback, useRef } from 'react';
import FileThumbnail from './FileThumbnail';

interface FileDropzoneProps {
  onFileSelect: (file: File) => void;
  onFileRemove: () => void;
  fileName: string | null;
  fileType: string | null;
  previewUrl: string | null;
}

export default function FileDropzone({ onFileSelect, onFileRemove, fileName, fileType, previewUrl }: FileDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDragEvents = (e: React.DragEvent<HTMLDivElement>, isEntering: boolean) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(isEntering);
  };

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    handleDragEvents(e, false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      onFileSelect(e.dataTransfer.files[0]);
      e.dataTransfer.clearData();
    }
  }, [onFileSelect]);
  
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
      onDragEnter={(e) => handleDragEvents(e, true)}
      onDragLeave={(e) => handleDragEvents(e, false)}
      onDragOver={(e) => e.preventDefault()}
      onDrop={handleDrop}
      onClick={() => fileInputRef.current?.click()}
    >
      <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />
      {fileName ? (
        <div className="relative flex flex-col items-center justify-center">
          <div onClick={(e) => e.stopPropagation()}>
            <FileThumbnail
              fileName={fileName}
              fileType={fileType}
              previewUrl={previewUrl}
            />
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onFileRemove();
            }}
            className="absolute top-2 right-2 bg-red-500 text-white rounded-full h-6 w-6 flex items-center justify-center font-bold"
          >
            &times;
          </button>
        </div>
      ) : (
        <div>
          <p className="text-gray-500">Drag & drop any file here</p>
          <p className="text-gray-400 text-sm">or click to select</p>
        </div>
      )}
    </div>
  );
}