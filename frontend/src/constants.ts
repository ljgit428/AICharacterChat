const DEFAULT_API_BASE_URL = "/api";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);
const runtimeHostname = typeof window !== "undefined" ? window.location.hostname : "";
const runtimeProtocol = typeof window !== "undefined" ? window.location.protocol : "http:";
const configuredApiBaseUrl = (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE_URL).replace(/\/$/, "");
const useDirectLocalBackend = LOCAL_HOSTS.has(runtimeHostname) && configuredApiBaseUrl === DEFAULT_API_BASE_URL;

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "AI Character Studio";
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || "dev";
export const API_BASE_URL = useDirectLocalBackend
  ? `${runtimeProtocol}//${runtimeHostname}:8000/api`
  : configuredApiBaseUrl;
export const GRAPHQL_API_URL = process.env.NEXT_PUBLIC_GRAPHQL_URL
  ? process.env.NEXT_PUBLIC_GRAPHQL_URL.replace(/\/$/, "")
  : useDirectLocalBackend
    ? `${API_BASE_URL}/graphql/`
    : `${API_BASE_URL}/graphql`;
export const UPLOAD_API_URL = useDirectLocalBackend ? `${API_BASE_URL}/upload/` : `${API_BASE_URL}/upload`;
export const MEDIA_BASE_URL = API_BASE_URL.replace(/\/api$/, "");
export const DEFAULT_PROJECT_MODEL_NAME = process.env.NEXT_PUBLIC_DEFAULT_MODEL_NAME || "default-model";
