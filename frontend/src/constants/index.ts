const DEFAULT_API_BASE_URL = "/api";
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1"]);
const runtimeHostname = typeof window !== "undefined" ? window.location.hostname : "";
const runtimeProtocol = typeof window !== "undefined" ? window.location.protocol : "http:";
const configuredApiBaseUrl = (process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_BASE_URL).replace(/\/$/, "");
const useDirectLocalBackend = LOCAL_HOSTS.has(runtimeHostname) && configuredApiBaseUrl === DEFAULT_API_BASE_URL;

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || "PrisMate";
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION || "dev";
export const API_BASE_URL = useDirectLocalBackend
  ? `${runtimeProtocol}//${runtimeHostname}:8000/api`
  : configuredApiBaseUrl;
// Django 路由全部带尾斜杠；POST 缺斜杠会触发 APPEND_SLASH 且无法重定向（500），
// 因此这里统一保证 URL 以单个斜杠结尾，代理模式的 rewrites 两种形式都能透传。
export const GRAPHQL_API_URL = process.env.NEXT_PUBLIC_GRAPHQL_URL
  ? `${process.env.NEXT_PUBLIC_GRAPHQL_URL.replace(/\/$/, "")}/`
  : `${API_BASE_URL}/graphql/`;
export const UPLOAD_API_URL = `${API_BASE_URL}/upload/`;
// Reference-file group uploads go to the dedicated file endpoint so they land
// under media/uploads/ (with folder hierarchy), not the avatar bucket.
export const FILES_UPLOAD_API_URL = `${API_BASE_URL}/files/upload/`;
export const MEDIA_BASE_URL = API_BASE_URL.replace(/\/api$/, "");
export const DEFAULT_PROJECT_MODEL_NAME = process.env.NEXT_PUBLIC_DEFAULT_MODEL_NAME || "default-model";
