import React, { useState, useCallback, useRef } from 'react';
import Image from 'next/image';

interface FileDropzoneProps {
  onFileSelect: (file: File) => void;
  onFileRemove: () => void;
  fileName: string | null;
  previewUrl: string | null; // New prop for image preview
}

export default function FileDropzone({ onFileSelect, onFileRemove, fileName, previewUrl }: FileDropzoneProps) {
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
      {previewUrl ? (
        <div className="relative flex flex-col items-center justify-center">
          <Image
            src={previewUrl}
            alt={fileName || 'Image Preview'}
            className="max-h-32 w-auto rounded-md object-contain"
            width={128}
            height={128}
          />
          <p className="mt-2 text-sm font-medium text-gray-700 truncate max-w-full px-8">{fileName}</p>
          <button
            onClick={(e) => { e.stopPropagation(); onFileRemove(); }}
            className="absolute top-0 right-0 -mt-2 -mr-2 bg-red-500 text-white rounded-full h-6 w-6 flex items-center justify-center font-bold"
          >
            &times;
          </button>
        </div>
      ) : fileName ? (
        <div className="relative flex flex-col items-center justify-center">
          <svg className="w-12 h-12 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
          <p className="text-sm font-medium text-gray-700 truncate max-w-full px-8">{fileName}</p>
          <button
            onClick={(e) => { e.stopPropagation(); onFileRemove(); }}
            className="absolute top-0 right-0 -mt-2 -mr-2 bg-red-500 text-white rounded-full h-6 w-6 flex items-center justify-center font-bold"
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