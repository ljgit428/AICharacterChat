import React from 'react';
import ImageMagnifier from './ImageMagnifier';

const PdfIcon = () => (<svg className="w-12 h-12 text-red-500" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM9.5 18H8v-2.12c0-.53.21-1.04.59-1.41l2.83-2.83c.38-.38.88-.59 1.41-.59s1.03.21 1.41.59l2.83 2.83c.38.38.59.88.59 1.41V18h-1.5v-2.12c0-.27-.11-.52-.29-.71l-2.12-2.12-2.12 2.12c-.18.19-.29.44-.29.71V18zm6-4.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z" /></svg>);
const DocIcon = () => (<svg className="w-12 h-12 text-blue-500" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM13 18H7v-2h6v2zm4-4H7v-2h10v2zm-2-4H7V8h8v2z" /></svg>);
const ZipIcon = () => (<svg className="w-12 h-12 text-yellow-500" viewBox="0 0 24 24" fill="currentColor"><path d="M20 6h-8l-2-2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2zm-6 8h-2v2h2v-2zm0-4h-2v2h2v-2zm0-4h-2v2h2V6z" /></svg>);
const TxtIcon = () => (<svg className="w-12 h-12 text-gray-500" viewBox="0 0 24 24" fill="currentColor"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM16 18H8v-2h8v2zm0-4H8v-2h8v2zm-3-4V3.5L18.5 9H13z" /></svg>);
const GenericFileIcon = () => (<svg className="w-12 h-12 text-gray-400" viewBox="0 0 24 24" fill="currentColor"><path d="M6 2c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm7 7V3.5L18.5 9H13z" /></svg>);

interface FileThumbnailProps {
  fileName: string | null;
  fileType?: string | null;
  previewUrl?: string | null;
}

const FileThumbnail: React.FC<FileThumbnailProps> = ({ fileName, fileType, previewUrl }) => {

  const getFileIcon = () => {
    if (!fileType) return <GenericFileIcon />;
    if (fileType.startsWith('application/pdf')) return <PdfIcon />;
    if (fileType.includes('word')) return <DocIcon />;
    if (fileType.startsWith('application/zip') || fileType.startsWith('application/x-zip')) return <ZipIcon />;
    if (fileType.startsWith('text/')) return <TxtIcon />;
    return <GenericFileIcon />;
  };

  const isImage = fileType
    ? fileType.startsWith('image/')
    : previewUrl && /\.(jpe?g|png|gif|webp|svg)$/i.test(previewUrl);

  if (previewUrl && isImage) {
    return (
      <div className="flex flex-col items-center justify-center w-full">
        <ImageMagnifier
          src={previewUrl}
          alt={fileName || 'Image preview'}
          width={128}
          height={128}
          className="max-h-32 w-auto rounded-md object-contain"
        />
        <p className="mt-2 text-xs font-medium text-gray-700 truncate max-w-full px-2">{fileName}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center p-2 bg-gray-100 rounded-lg w-full">
      {getFileIcon()}
      <p className="mt-2 text-xs font-medium text-gray-700 truncate max-w-full px-2">{fileName}</p>
    </div>
  );
};

export default FileThumbnail;