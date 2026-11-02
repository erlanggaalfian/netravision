/* Tipe bersama — cerminan kontrak packages/contracts/openapi.yaml */

export interface Stream {
  id: number;
  name: string;
  brand: string | null;
  is_online: boolean;
  is_active: boolean;
  last_seen_at: string | null;
  whep_main_url: string | null;
  whep_sub_url: string | null;
  poster_url: string | null;
  storage_mode: string;
  drive_account_id: string | null;
  latitude: number | null;
  longitude: number | null;
  recording_enabled: boolean;
  retention_days: number;
}

export interface DriveAccount {
  id: string;
  name: string;
  is_default: boolean;
  connected: boolean;
  status: "pending" | "connected" | "error";
  last_error: string | null;
  camera_count: number;
  created_at: string;
}

export interface User {
  id: number;
  username: string;
  role: "admin" | "user" | "guest" | "super_admin";
  is_active: boolean;
  show_ads: boolean;
  dibuat_oleh?: string | null;
}

export interface AdConfig {
  image_url: string;
  marquee_text: string;
  bg_color: string;
  text_color: string;
  scroll_speed: number;
  font_size: number;
  font_family: string;
  image_opacity: number;
  bg_opacity: number;
  text_opacity: number;
  is_active: boolean;
  box_width: number;
  text_align: string;
  image_height: number;
  embed_timeout_seconds: number;
  click_to_play: boolean;
}

export interface Group {
  id: number;
  name: string;
  description: string | null;
}

export interface ApiKey {
  id: number;
  name: string;
  last_used_at: string | null;
  domain_lock: string | null;
  is_active: boolean;
  stream_ids: number[];
  custom_camera_name: string;
  include_playback: boolean;
}

export interface DiskInfo {
  path: string;
  measured_on: string;
  total: number;
  used: number;
  free: number;
}

export interface ScanCandidate {
  main_url: string;
  sub_url: string | null;
  brand: string;
  method: string;
}

export interface StatusChange {
  stream_id: number;
  is_online: boolean;
}
