export type FieldKind = "text" | "password" | "number" | "select" | "checkbox";
export type FieldValue = string | number | boolean | null;

export interface FieldSpec {
  name: string;
  kind: FieldKind;
  required: boolean;
  secret: boolean;
  default: FieldValue;
  options: string[];
  min: number | null;
  max: number | null;
}

export interface CameraProviderSpec {
  id: string;
  transport: "local" | "cloud";
  account_provider: string | null;
  fields: FieldSpec[];
}

export interface AccountProviderSpec {
  id: string;
  fields: FieldSpec[];
}

export interface ProvidersResponse {
  cameras: CameraProviderSpec[];
  accounts: AccountProviderSpec[];
}

export type CameraStatus = "unknown" | "online" | "sleeping" | "offline" | "needs_setup" | "unsupported" | "quota";

export interface StreamProbe {
  codec: string | null;
  width: number | null;
  height: number | null;
  fps: number | null;
}

export interface Camera {
  id: number;
  name: string;
  location: string;
  group: string;
  provider: string;
  account_id: number | null;
  favourite: boolean;
  transport: "local" | "cloud";
  capabilities: { transport: string; streams: string[]; snapshot: boolean; battery: boolean };
  status: CameraStatus;
  status_code: string | null;
  last_seen_at: string | null;
  last_checked_at: string | null;
  verified: boolean;
  probe: { main_probe?: StreamProbe; sub_probe?: StreamProbe };
  config?: Record<string, FieldValue>;
  secrets_set?: string[];
}

export interface Account {
  id: number;
  name: string;
  provider: string;
  config: Record<string, FieldValue>;
  secrets_set: string[];
}

export interface DiagStep {
  name: string;
  status: "pass" | "fail" | "skip";
  code: string | null;
  detail: Record<string, unknown>;
}

export interface Diagnostics {
  ok: boolean;
  steps: DiagStep[];
  discovered: Record<string, unknown>;
}

export interface ImouDevice {
  device_id: string;
  channel_id: string;
  name: string;
  added: boolean;
}
