## Version History


### v0.0.4
- **Gemini File API Integration**: Implemented advanced file handling using Google's Gemini File API instead of local file storage
- **Character background documents**: Characters can now upload files (PDF, TXT, images) as background knowledge that AI can reference during conversations
- **Database schema changes**: Added `gemini_file_ref` field to Character model to store file references
- **Enhanced file upload**: Files are uploaded directly to Google's servers and referenced by handles
- **Improved Celery tasks**: Updated to reference uploaded files using Gemini handles instead of reading local files
- **Better error handling**: Proper handling of InMemoryUploadedFile objects and Windows file locking issues
- **Form data support**: Added proper parser classes to chat endpoint for handling form data
- **File cleanup**: Implemented proper temporary file cleanup to prevent resource leaks
- **Multi-modal support**: System now supports various file types (PDFs, images, audio) for character background
- **Scalability**: Files are uploaded once and referenced efficiently, reducing bandwidth usage

- **Asynchronous Processing**: Fixed critical synchronous vs asynchronous processing issue in ChatViewSet - now properly uses Celery's `.delay()` method for AI response generation
- **Improved Performance**: Eliminated UI blocking during AI response generation by returning immediate `status: 'processing'` responses
- **Enhanced File Handling**: Replaced risky temporary file handling with robust `with tempfile.NamedTemporaryFile()` approach to prevent Windows file locking issues
- **FormData Support**: Updated frontend API service to properly handle FormData for file uploads with conditional Content-Type headers
- **Character File Uploads**: Enhanced CharacterSettings component with file input support for background documents
- **TypeScript Improvements**: Added proper interfaces for ChatResponse, AIResponse, and ChatSession types with strong typing
- **Backend Robustness**: Improved system stability with better error handling and resource management
- **Frontend Backend Sync**: Ensured frontend and backend interfaces are properly synchronized for character creation/update with FormData
- **Build Optimization**: Resolved TypeScript and ESLint errors for successful production builds
- **User Experience**: Users can now upload character background documents without UI freezing during AI processing

### v0.0.2
- **Enhanced API message handling**: Added robust support for receiving and processing completed API messages
- **Authentication system**: Implemented user authentication views and login modal component
- **Docker support**: Added docker-compose.yml for easy Redis deployment
- **Improved documentation**: Added development difficulties guide and testing guide
- **Backend optimizations**: Enhanced Celery configuration and task management
- **Frontend improvements**: Updated Next.js configuration and component structure
- **Environment security**: Improved .gitignore configuration to prevent cache file commits