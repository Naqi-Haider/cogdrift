export interface Flag {
  flag_id: string;
  patient_id: string;
  created_at: string;
  date: string;
  detector_type: 'TREND' | 'PATTERN' | 'BOTH';
  severity: 'HIGH' | 'MODERATE' | 'LOW';
  z_score?: number | null;
  isolation_score?: number | null;
  status: 'pending' | 'confirmed' | 'dismissed' | 'needs_more_data';
  explanation: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  clinician_notes?: string | null;
  disclaimer: string;
  recurrence_count?: number;
}

export interface AnomalyMarker {
  date: string;
  flag_id: string;
  detector_type: string;
  status: string;
  z_score?: number | null;
  isolation_score?: number | null;
}

export interface TrendPoint {
  date: string;
  daily_cognitive_score: number;
  rolling_mean?: number | null;
  rolling_std?: number | null;
  upper_bound?: number | null;
  lower_bound?: number | null;
  z_score?: number | null;
  is_anomaly: boolean;
}

export interface TrendResponse {
  patient_id: string;
  points: TrendPoint[];
  anomalies?: AnomalyMarker[];
}

export interface CaregiverMessage {
  flag_id: string;
  patient_id: string;
  date: string;
  reviewed_at?: string | null;
  clinician_approved_message: string;
  disclaimer: string;
}
