import React, { useState, useEffect } from 'react';
import { CaregiverMessage } from '../types';
import { HeartHandshake, Calendar, CheckCircle2, UserCheck, ShieldCheck, Mail, Clock } from 'lucide-react';

interface CaregiverViewProps {
  apiBaseUrl?: string;
  caregiverToken?: string;
  patientId: string;
}

export const CaregiverView: React.FC<CaregiverViewProps> = ({
  apiBaseUrl = 'http://localhost:8000',
  caregiverToken = '',
  patientId = 'P0004',
}) => {
  const [messages, setMessages] = useState<CaregiverMessage[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!caregiverToken || !patientId) return;

    setLoading(true);
    // Fetch clinician-approved care messages for caregiver
    fetch(`${apiBaseUrl}/caregiver/${patientId}/messages`, {
      headers: {
        Authorization: `Bearer ${caregiverToken}`,
      },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Status ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setMessages(data);
        setError(null);
      })
      .catch((err) => {
        setError(`Could not fetch caregiver updates: ${err.message}`);
      })
      .finally(() => setLoading(false));
  }, [apiBaseUrl, caregiverToken, patientId]);

  return (
    <div className="bg-white border border-[#e1eae3] rounded-3xl p-6 shadow-nh-card space-y-6 max-w-5xl mx-auto">
      {/* Standardized Summary Cards Grid (P2 Item 11) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Card 1: Portal Identity */}
        <div className="bg-white border border-[#e1eae3] rounded-2xl p-4 flex items-center space-x-3 shadow-sm">
          <div className="p-3 bg-nh-green-light text-nh-green-deep rounded-xl">
            <HeartHandshake className="w-6 h-6" />
          </div>
          <div>
            <span className="text-[11px] font-bold text-nh-green-accent uppercase tracking-wider block">
              CAREGIVER PORTAL
            </span>
            <h3 className="text-base font-bold text-nh-text-main">
              Care Guidance Feed
            </h3>
          </div>
        </div>

        {/* Card 2: Active Patient & Plain-Language Wording (P1 Item 8) */}
        <div className="bg-white border border-[#e1eae3] rounded-2xl p-4 flex items-center justify-between shadow-sm">
          <div>
            <span className="text-[11px] font-bold text-nh-text-muted uppercase tracking-wider block">
              Active Patient
            </span>
            <span className="text-xl font-extrabold text-nh-green-deep font-mono">
              Patient {patientId}
            </span>
          </div>
          {/* Plain Language Status Wording: "Up to date" or "X Care Updates Available" */}
          <span className="text-xs bg-emerald-100 text-emerald-800 font-bold px-3 py-1.5 rounded-full border border-emerald-200">
            {messages.length === 0 ? 'Up to date' : `${messages.length} Care Updates Available`}
          </span>
        </div>

        {/* Card 3: Clinician Oversight Summary */}
        <div className="bg-white border border-[#e1eae3] rounded-2xl p-4 flex items-center justify-between shadow-sm">
          <div className="flex items-center space-x-3">
            <div className="p-3 bg-nh-green-light text-nh-green-deep rounded-xl">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <span className="text-[11px] font-bold text-nh-green-accent uppercase tracking-wider block">
                CLINICAL OVERSIGHT
              </span>
              <span className="text-xs font-bold text-nh-text-main block">
                Human-in-the-Loop Verified
              </span>
            </div>
          </div>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-amber-50 border border-amber-200 text-amber-800 rounded-2xl text-xs">
          {error}
        </div>
      )}

      {/* Guidance Timeline Feed */}
      {loading ? (
        <div className="h-48 flex items-center justify-center text-xs text-nh-text-muted">
          Loading caregiver updates...
        </div>
      ) : messages.length === 0 ? (
        /* Constrained Empty State with Meaningful Care Content (P2 Item 9) */
        <div className="p-8 bg-[#f8faf8] rounded-2xl border border-dashed border-[#d8e5dc] space-y-6">
          <div className="text-center max-w-md mx-auto">
            <CheckCircle2 className="w-12 h-12 text-nh-green-mint mx-auto mb-3" />
            <h4 className="font-bold text-nh-text-main text-lg">No New Care Updates Needed</h4>
            <p className="text-xs text-nh-text-muted mt-1 leading-relaxed">
              Your patient's cognitive exercise activities are being monitored continuously. If an unusual pattern is confirmed by their supervising clinician, verified guidance notes will appear here immediately.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-4 border-t border-[#e2ebe4]">
            <div className="bg-white p-4 rounded-xl border border-[#e1eae3] flex items-start space-x-3">
              <Clock className="w-5 h-5 text-nh-green-accent flex-shrink-0 mt-0.5" />
              <div>
                <span className="text-xs font-bold text-nh-text-main block">Monitoring Sync Status</span>
                <span className="text-[11px] text-nh-text-muted block">Last data sync: Today at 08:00 AM</span>
                <span className="text-[11px] text-nh-green-deep font-semibold block mt-1">Status: Active & Continuous</span>
              </div>
            </div>

            <div className="bg-white p-4 rounded-xl border border-[#e1eae3] flex items-start space-x-3">
              <Mail className="w-5 h-5 text-nh-green-accent flex-shrink-0 mt-0.5" />
              <div>
                <span className="text-xs font-bold text-nh-text-main block">Clinical Care Team</span>
                <span className="text-[11px] text-nh-text-muted block">Need to reach your supervising clinician?</span>
                <button className="text-[11px] font-bold text-nh-green-deep hover:underline mt-1 block">
                  Contact Care Team Support &rarr;
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4 max-h-[500px] overflow-y-auto pr-1">
          <div className="text-xs font-bold text-nh-green-deep uppercase tracking-wider px-1">
            Confirmed Care History ({messages.length} Permanent Records)
          </div>
          {messages.map((msg, index) => (
            <div key={msg.flag_id} className="p-5 rounded-2xl bg-[#f8faf8] border border-[#e2ebe4] space-y-3 shadow-sm">
              <div className="flex items-center justify-between border-b border-[#edf3ee] pb-2">
                <span className="text-xs font-extrabold text-nh-green-deep flex items-center gap-1.5">
                  <UserCheck className="w-4 h-4 text-nh-green-accent" />
                  Clinician Approved Guidance #{messages.length - index}
                </span>
                <span className="text-xs text-nh-text-muted font-mono flex items-center gap-1">
                  <Calendar className="w-3.5 h-3.5 text-nh-green-accent" />
                  {msg.reviewed_at ? new Date(msg.reviewed_at).toLocaleDateString() : msg.date}
                </span>
              </div>

              <div className="p-4 bg-white rounded-xl border border-[#e1eae3] text-xs text-nh-text-main leading-relaxed shadow-sm">
                {msg.clinician_approved_message}
              </div>

              {/* Shared Warning Token Styling */}
              <div className="text-[11px] text-amber-900 bg-amber-50 p-2.5 rounded-xl border border-amber-200 font-medium">
                ⚠️ {msg.disclaimer}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
