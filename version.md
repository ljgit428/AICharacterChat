## Version History


### v0.0.4
- **Multiple Background Files**: Enhanced character system to support multiple background documents per character (replaced one-to-one relationship with one-to-many)
- **Advanced File Management**: Implemented comprehensive file management interface with upload, display, and delete functionality
- **Database Architecture**: Redesigned database schema with new `CharacterFile` model to handle multiple file relationships
- **Backend API Enhancements**: Updated all related APIs to handle multiple file uploads and individual file deletion
- **File Deletion System**: Added robust file deletion that removes files from both Google Gemini API and database
- **Multi-File Upload Support**: Characters can now upload multiple documents simultaneously for richer AI context
- **Improved User Interface**: Enhanced CharacterSettings component with file lists, visual distinction between existing/new files, and individual delete buttons
- **TypeScript Integration**: Added comprehensive type definitions for `CharacterFile` interface and updated existing `Character` interface
- **API Service Expansion**: Extended API service with `deleteCharacterFile` method for file management operations
- **Celery Task Updates**: Enhanced AI response generation to process and utilize multiple background files for more contextual conversations
- **Frontend State Management**: Optimized state handling for both existing and newly selected files with real-time UI updates
- **Backward Compatibility**: Maintained compatibility with existing characters while adding new functionality
- **Migration System**: Implemented proper database migration to transition from single to multiple file architecture

### v0.0.2
- **Enhanced API message handling**: Added robust support for receiving and processing completed API messages
- **Authentication system**: Implemented user authentication views and login modal component
- **Docker support**: Added docker-compose.yml for easy Redis deployment
- **Improved documentation**: Added development difficulties guide and testing guide
- **Backend optimizations**: Enhanced Celery configuration and task management
- **Frontend improvements**: Updated Next.js configuration and component structure
- **Environment security**: Improved .gitignore configuration to prevent cache file commits