/* Tipe bersama — cerminan kontrak packages/contracts/openapi.yaml */

export interface Stream {
  id: number;
  name: string;
  brand: string | null;
  is_online: boolean;
  last_seen_at: string | null;
  whep_main_url: string | null;
  whep_sub_url: string | null;
  poster_url: string | null;
  storage_mode: string;
  drive_account_id: string | null;
  latitude: number | null;
  longitude: number | null;
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
  role: "admin" | "user" | "guest";
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
