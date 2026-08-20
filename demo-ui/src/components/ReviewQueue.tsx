import React, { useState, useEffect } from 'react';
import { Flag } from '../types';
import { CheckCircle, XCircle, HelpCircle, Clock, RefreshCw, Activity, Filter, ShieldAlert, ArrowUpDown, CheckSquare, Square } from 'lucide-react';

interface ReviewQueueProps {
  apiBaseUrl?: string;
  clinicianToken?: string;
  selectedPatientId?: string;
  onSelectPatient?: (patientId: string) => void;
}

export const ReviewQueue: React.FC<ReviewQueueProps> = ({
  apiBaseUrl = 'http://localhost:8000',
  clinicianToken = '',
  selectedPatientId,
  onSelectPatient,
}) => {
  const [flags, setFlags] = useState<Flag[]>([]);
  const [totalInitialCount, setTotalInitialCount] = useState<number>(16);
  const [reviewedTodayCount, setReviewedTodayCount] = useState<number>(0);
  const [loading, setLoading] = useState<boolean>(true);
  const [selectedFlag, setSelectedFlag] = useState<Flag | null>(null);
  const [notes, setNotes] = useState<string>('');
  const [reviewing, setReviewing] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Queue Scope Filter: 'ALL' or 'SELECTED'
  const [queueScope, setQueueScope] = useState<'ALL' | 'SELECTED'>('ALL');
  // Severity Filter: 'ALL' | 'HIGH' | 'MODERATE' | 'LOW'
  const [severityFilter, setSeverityFilter] = useState<'ALL' | 'HIGH' | 'MODERATE' | 'LOW'>('ALL');
  // Sort Order: 'SEVERITY' | 'NEWEST'
  const [sortBy, setSortBy] = useState<'SEVERITY' | 'NEWEST'>('SEVERITY');
  // Multi-Select for Bulk Action on LOW severity signals
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [bulkReviewing, setBulkReviewing] = useState<boolean>(false);

  const fetchFlags = async () => {
    try {
      setError(null);
      const url = `${apiBaseUrl}/flags?status=pending`;

      const res = await fetch(url, {
        headers: {
          Authorization: `Bearer ${clinicianToken}`,
        },
      });
      if (!res.ok) {
        throw new Error(`API ${res.status}: ${res.statusText}`);
      }
      const data: Flag[] = await res.json();
      setFlags(data);
      if (data.length > totalInitialCount) {
        setTotalInitialCount(data.length);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to fetch review queue');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (clinicianToken) {
      fetchFlags();
    }
  }, [clinicianToken, apiBaseUrl]);

  const handleReview = async (decision: 'confirmed' | 'dismissed' | 'needs_more_data') => {
    if (!selectedFlag) return;
    setReviewing(true);
    setError(null);
    try {
      const res = await fetch(`${apiBaseUrl}/flags/${selectedFlag.flag_id}/review`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${clinicianToken}`,
        },
        body: JSON.stringify({
          decision,
          notes: notes || undefined,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Review failed with status ${res.status}`);
      }

      // Remove reviewed flag from active list and update progress counter
      setFlags((prev) => prev.filter((f) => f.flag_id !== selectedFlag.flag_id));
      setSelectedIds((prev) => prev.filter((id) => id !== selectedFlag.flag_id));
      setReviewedTodayCount((prev) => prev + 1);
      setSelectedFlag(null);
      setNotes('');
    } catch (err: any) {
      // Preserve typed notes and selectedFlag on error so clinician can revise in place
      setError(err.message || 'Review failed');
    } finally {
      setReviewing(false);
    }
  };

  const handleBulkDismiss = async () => {
    if (selectedIds.length === 0) return;
    setBulkReviewing(true);
    try {
      const res = await fetch(`${apiBaseUrl}/flags/bulk-review`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${clinicianToken}`,
        },
        body: JSON.stringify({
          flag_ids: selectedIds,
          decision: 'dismissed',
          notes: 'Bulk dismissed routine low-severity signals',
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || `Status ${res.status}`);
      }

      setFlags((prev) => prev.filter((f) => !selectedIds.includes(f.flag_id)));
      setReviewedTodayCount((prev) => prev + selectedIds.length);
      setSelectedIds([]);
    } catch (err: any) {
      alert(`Bulk action error: ${err.message}`);
    } finally {
      setBulkReviewing(false);
    }
  };

  const toggleSelect = (id: string, severity: string) => {
    if (severity === 'HIGH' || severity === 'MODERATE') {
      alert('Single-item review is mandatory for HIGH or MODERATE severity flags. Bulk review is restricted to LOW severity signals.');
      return;
    }
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  // Count patient occurrences for recurrence indicators
  const patientFlagCounts: Record<string, number> = {};
  flags.forEach((f) => {
    patientFlagCounts[f.patient_id] = (patientFlagCounts[f.patient_id] || 0) + 1;
  });

  // Count flags for currently selected patient
  const selectedPatientFlagsCount = flags.filter(
    (f) => f.patient_id === selectedPatientId
  ).length;

  // Filtered & Sorted flags
  const processedFlags = flags
    .filter((f) => (queueScope === 'SELECTED' ? f.patient_id === selectedPatientId : true))
    .filter((f) => (severityFilter === 'ALL' ? true : f.severity === severityFilter))
    .sort((a, b) => {
      if (sortBy === 'SEVERITY') {
        const rank = { HIGH: 3, MODERATE: 2, LOW: 1 };
        return (rank[b.severity] || 0) - (rank[a.severity] || 0);
      }
      return new Date(b.date).getTime() - new Date(a.date).getTime();
    });

  return (
    <div className="bg-white border border-[#e1eae3] rounded-3xl p-6 shadow-nh-card space-y-5">
      {/* Top Header & Progress Indicator */}
      <div className="flex items-center justify-between border-b border-[#edf3ee] pb-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="text-[11px] font-bold tracking-wider text-nh-green-accent uppercase block">
              CLINICIAN WORKFLOW QUEUE
            </span>
            {/* Progress Indicator ("N of 16 reviewed today") */}
            <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200 font-mono">
              {reviewedTodayCount} of {totalInitialCount} reviewed today
            </span>
          </div>
          <h3 className="text-xl font-bold text-nh-text-main flex items-center gap-2 mt-1">
            Pending Signals
            <span className="text-xs px-2.5 py-0.5 rounded-full bg-nh-green-light text-nh-green-deep font-bold border border-[#d2e4d8]">
              {flags.length} pending
            </span>
          </h3>
        </div>

        <button
          onClick={fetchFlags}
          className="p-2 text-nh-text-muted hover:text-nh-green-deep bg-nh-green-subtle hover:bg-nh-green-light rounded-full transition-colors"
          title="Refresh Queue"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Scope Filter Tabs */}
      <div className="flex items-center justify-between bg-nh-green-subtle p-1 rounded-2xl border border-[#d8e5dc]">
        <button
          onClick={() => setQueueScope('ALL')}
          className={`flex-1 py-1.5 rounded-xl text-xs font-bold transition-all text-center ${
            queueScope === 'ALL'
              ? 'bg-nh-green-deep text-white shadow-sm'
              : 'text-nh-text-muted hover:text-nh-green-deep'
          }`}
        >
          All Patients Queue ({flags.length})
        </button>
        <button
          onClick={() => setQueueScope('SELECTED')}
          className={`flex-1 py-1.5 rounded-xl text-xs font-bold transition-all text-center flex items-center justify-center gap-1 ${
            queueScope === 'SELECTED'
              ? 'bg-nh-green-deep text-white shadow-sm'
              : 'text-nh-text-muted hover:text-nh-green-deep'
          }`}
        >
          <Filter className="w-3 h-3" />
          Selected: {selectedPatientId || 'P0004'} ({selectedPatientFlagsCount})
        </button>
      </div>

      {/* Severity Filter & Sort Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-[#f8faf8] p-2 rounded-2xl border border-[#e2ebe4]">
        <div className="flex items-center space-x-1">
          <span className="text-[10px] font-bold text-nh-text-muted uppercase px-1">Severity:</span>
          {(['ALL', 'HIGH', 'MODERATE', 'LOW'] as const).map((sev) => (
            <button
              key={sev}
              onClick={() => setSeverityFilter(sev)}
              className={`px-2.5 py-1 rounded-lg text-[10px] font-bold transition-all ${
                severityFilter === sev
                  ? 'bg-nh-green-deep text-white shadow-xs'
                  : 'bg-white text-nh-text-muted hover:text-nh-green-deep border border-[#e2ebe4]'
              }`}
            >
              {sev}
            </button>
          ))}
        </div>

        <div className="flex items-center space-x-1">
          <button
            onClick={() => setSortBy(sortBy === 'SEVERITY' ? 'NEWEST' : 'SEVERITY')}
            className="px-2.5 py-1 bg-white border border-[#e2ebe4] hover:bg-slate-50 text-[10px] font-bold text-nh-text-main rounded-lg flex items-center gap-1 transition-colors"
          >
            <ArrowUpDown className="w-3 h-3 text-nh-green-accent" />
            Sort: {sortBy === 'SEVERITY' ? 'Highest Severity' : 'Newest'}
          </button>
        </div>
      </div>

      {/* Multi-Select Bulk Action Bar */}
      {selectedIds.length > 0 && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-center justify-between text-xs animate-fadeIn">
          <span className="font-bold text-emerald-900 flex items-center gap-1">
            <CheckSquare className="w-4 h-4 text-emerald-700" />
            {selectedIds.length} low-severity signal{selectedIds.length > 1 ? 's' : ''} selected
          </span>
          <button
            onClick={handleBulkDismiss}
            disabled={bulkReviewing}
            className="px-3.5 py-1.5 bg-emerald-700 hover:bg-emerald-800 text-white text-xs font-bold rounded-xl transition-colors shadow-sm flex items-center gap-1"
          >
            <XCircle className="w-3.5 h-3.5" />
            Bulk Mark Reviewed ({selectedIds.length})
          </button>
        </div>
      )}

      {error && (
        <div className="p-3 bg-amber-50 border border-amber-200 text-amber-800 text-xs rounded-xl">
          {error}
        </div>
      )}

      {/* Queue List */}
      {loading && flags.length === 0 ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="p-4 bg-white border border-[#e1eae3] rounded-2xl shadow-xs space-y-3 animate-pulse"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2.5">
                  <div className="w-8 h-8 rounded-full bg-slate-200" />
                  <div className="space-y-1">
                    <div className="h-3.5 w-20 bg-slate-200 rounded" />
                    <div className="h-2.5 w-14 bg-slate-100 rounded" />
                  </div>
                </div>
                <div className="h-5 w-16 bg-slate-200 rounded-full" />
              </div>
              <div className="h-3 w-3/4 bg-slate-100 rounded" />
            </div>
          ))}
        </div>
      ) : processedFlags.length === 0 ? (
        <div className="h-56 flex flex-col items-center justify-center text-nh-text-muted text-sm bg-nh-green-subtle/40 rounded-2xl border border-dashed border-[#d8e5dc] p-6 text-center">
          <CheckCircle className="w-10 h-10 text-nh-green-mint mb-2" />
          <span className="font-semibold text-nh-text-main text-base">Review Queue Clear</span>
          <p className="text-xs text-nh-text-muted mt-1 max-w-xs mb-3">
            {queueScope === 'SELECTED'
              ? `No pending signals for Patient ${selectedPatientId}.`
              : 'All pending anomaly signals have been reviewed.'}
          </p>
        </div>
      ) : (
        <div className="space-y-4 max-h-[500px] overflow-y-auto pr-1">
          {processedFlags.map((flag) => {
            const isSelected = selectedFlag?.flag_id === flag.flag_id;
            const isChecked = selectedIds.includes(flag.flag_id);
            const recurrenceCount = patientFlagCounts[flag.patient_id] || 1;

            // Shared color tokens for severity and metrics
            const severityColor =
              flag.severity === 'HIGH'
                ? 'bg-red-100 text-red-800 border-red-200'
                : flag.severity === 'MODERATE'
                ? 'bg-amber-100 text-amber-800 border-amber-200'
                : 'bg-emerald-100 text-emerald-800 border-emerald-200';

            const zColor =
              flag.z_score !== undefined && flag.z_score !== null && flag.z_score <= -2.5
                ? 'text-red-600 font-extrabold'
                : flag.z_score !== undefined && flag.z_score !== null && flag.z_score <= -2.0
                ? 'text-amber-600 font-extrabold'
                : 'text-nh-text-main font-bold';

            const isoColor =
              flag.isolation_score !== undefined && flag.isolation_score !== null && flag.isolation_score <= -0.05
                ? 'text-red-600 font-extrabold'
                : flag.isolation_score !== undefined && flag.isolation_score !== null && flag.isolation_score < 0
                ? 'text-amber-600 font-extrabold'
                : 'text-nh-text-main font-bold';

            return (
              <div
                key={flag.flag_id}
                className={`p-5 rounded-2xl border transition-all relative ${
                  isSelected
                    ? 'bg-white border-nh-green-deep shadow-nh-lift ring-2 ring-nh-green-deep/20'
                    : isChecked
                    ? 'bg-emerald-50/50 border-emerald-300'
                    : 'bg-[#f8faf8] border-[#e2ebe4] hover:border-[#b5d1be]'
                }`}
              >
                {/* Top Row: Checkbox + Patient ID + Severity Chip + Recurrence Badge */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2.5">
                    {/* Multi-Select Checkbox for LOW severity signals */}
                    <button
                      onClick={() => toggleSelect(flag.flag_id, flag.severity)}
                      className={`p-1 rounded-md transition-colors ${
                        flag.severity === 'HIGH' || flag.severity === 'MODERATE'
                          ? 'opacity-40 cursor-not-allowed text-slate-300'
                          : 'text-emerald-700 hover:bg-emerald-100'
                      }`}
                      title={
                        flag.severity === 'HIGH' || flag.severity === 'MODERATE'
                          ? 'Single-item review mandatory for HIGH or MODERATE severity'
                          : 'Select for bulk action'
                      }
                    >
                      {isChecked ? (
                        <CheckSquare className="w-4 h-4 text-emerald-700" />
                      ) : (
                        <Square className="w-4 h-4 text-slate-400" />
                      )}
                    </button>

                    <button
                      onClick={() => onSelectPatient && onSelectPatient(flag.patient_id)}
                      className="font-extrabold text-nh-green-deep hover:underline text-sm flex items-center gap-1"
                    >
                      <Activity className="w-3.5 h-3.5" />
                      Patient {flag.patient_id}
                    </button>

                    {/* Server-Computed Severity Chip */}
                    <span className={`text-[10px] font-extrabold px-2.5 py-0.5 rounded-full border uppercase ${severityColor}`}>
                      {flag.severity}
                    </span>

                    {/* Recurrence Indicator */}
                    {recurrenceCount > 1 && (
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-purple-100 text-purple-900 border border-purple-200">
                        {recurrenceCount}nd flag this week
                      </span>
                    )}
                  </div>

                  <span className="text-xs text-nh-text-muted font-mono flex items-center">
                    <Clock className="w-3.5 h-3.5 mr-1 text-nh-green-accent" />
                    {flag.date}
                  </span>
                </div>

                {/* Metric Badges with Shared Dual Color-Coding */}
                <div className="grid grid-cols-2 gap-2 mb-3">
                  {flag.z_score !== undefined && flag.z_score !== null && (
                    <div className="bg-white p-2 rounded-xl border border-[#e2ebe4] text-xs">
                      <span className="text-nh-text-muted text-[10px] uppercase font-bold block">Z-Score</span>
                      <span className={zColor}>{Math.round(flag.z_score * 100) / 100}</span>
                    </div>
                  )}
                  {flag.isolation_score !== undefined && flag.isolation_score !== null && (
                    <div className="bg-white p-2 rounded-xl border border-[#e2ebe4] text-xs">
                      <span className="text-nh-text-muted text-[10px] uppercase font-bold block">Isolation Score</span>
                      <span className={isoColor}>{Math.round(flag.isolation_score * 1000) / 1000}</span>
                    </div>
                  )}
                </div>

                {/* Natural Language Explanation Box */}
                <div className="bg-white p-3.5 rounded-xl border border-[#e2ebe4] text-xs text-nh-text-main leading-relaxed mb-3">
                  {flag.explanation}
                </div>

                {/* Review Form */}
                {isSelected ? (
                  <div className="space-y-3 pt-3 border-t border-[#e2ebe4]">
                    {error && (
                      <div className="p-2.5 bg-red-50 border border-red-200 text-red-800 rounded-xl text-xs font-semibold flex items-center justify-between">
                        <span>{error}</span>
                        <button onClick={() => setError(null)} className="text-red-600 font-bold text-xs ml-2">Dismiss</button>
                      </div>
                    )}

                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between">
                        <label className="text-[11px] font-bold text-nh-green-deep uppercase block">
                          Caregiver Guidance Note (Permanent Record):
                        </label>
                        <span className="text-[10px] text-slate-500 font-mono">Pattern-Screened</span>
                      </div>

                      {/* Quick Non-Clinical Templates */}
                      <div className="flex flex-wrap gap-1.5 mb-1.5">
                        <span className="text-[10px] font-bold text-nh-text-muted w-full block">Pre-Approved Non-Clinical Templates:</span>
                        <button
                          type="button"
                          onClick={() => setNotes("Continue daily rehabilitation exercise sessions as scheduled.")}
                          className="text-[10px] bg-emerald-50 text-emerald-800 border border-emerald-200 px-2.5 py-1 rounded-full hover:bg-emerald-100 font-medium transition-colors"
                        >
                          + Routine Exercises
                        </button>
                        <button
                          type="button"
                          onClick={() => setNotes("Exercise engagement has dropped; recommend checking in with the patient.")}
                          className="text-[10px] bg-emerald-50 text-emerald-800 border border-emerald-200 px-2.5 py-1 rounded-full hover:bg-emerald-100 font-medium transition-colors"
                        >
                          + Engagement Check-In
                        </button>
                        <button
                          type="button"
                          onClick={() => setNotes("Recommend scheduling a routine follow-up visit with the clinical care team.")}
                          className="text-[10px] bg-emerald-50 text-emerald-800 border border-emerald-200 px-2.5 py-1 rounded-full hover:bg-emerald-100 font-medium transition-colors"
                        >
                          + Schedule Follow-up
                        </button>
                      </div>

                      <textarea
                        value={notes}
                        onChange={(e) => {
                          setError(null);
                          setNotes(e.target.value);
                        }}
                        placeholder="Enter non-clinical activity or engagement guidance for caregiver..."
                        className="w-full bg-[#f8faf8] border border-[#cbd8cf] rounded-xl p-3 text-xs text-nh-text-main placeholder-nh-text-light focus:outline-none focus:border-nh-green-deep focus:ring-1 focus:ring-nh-green-deep"
                        rows={3}
                      />

                      {/* Real-Time Medication Pattern Warning */}
                      {/\b(\d+\s*mg|\d+\s*mcg|dosage|dose|prescrib|medication|pill|tablet|donepezil|memantine|aricept)\b/i.test(notes) && (
                        <div className="p-2.5 bg-red-50 border border-red-200 text-red-800 rounded-xl text-[11px] font-medium flex items-center gap-1.5 shadow-xs">
                          <ShieldAlert className="w-4 h-4 text-red-600 shrink-0" />
                          <span>This field is for activity and engagement guidance only. Medication changes must go through your clinical prescribing system.</span>
                        </div>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <button
                        onClick={() => setSelectedFlag(null)}
                        className="px-3 py-1.5 text-xs text-nh-text-muted font-medium hover:text-nh-text-main"
                        disabled={reviewing}
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => handleReview('dismissed')}
                        disabled={reviewing}
                        className="px-3.5 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-full transition-colors flex items-center gap-1"
                      >
                        <XCircle className="w-3.5 h-3.5 text-slate-500" />
                        Dismiss
                      </button>
                      <button
                        onClick={() => handleReview('needs_more_data')}
                        disabled={reviewing}
                        className="px-3.5 py-1.5 bg-amber-50 hover:bg-amber-100 text-amber-900 border border-amber-200 text-xs font-semibold rounded-full transition-colors flex items-center gap-1"
                      >
                        <HelpCircle className="w-3.5 h-3.5 text-amber-700" />
                        Request Data
                      </button>
                      <button
                        onClick={() => handleReview('confirmed')}
                        disabled={reviewing}
                        className="px-4 py-1.5 bg-nh-green-deep hover:bg-nh-green-hover text-white text-xs font-semibold rounded-full transition-colors shadow-sm flex items-center gap-1"
                      >
                        <CheckCircle className="w-3.5 h-3.5 text-white" />
                        Confirm Signal
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="pt-2 flex justify-end">
                    <button
                      onClick={() => {
                        setSelectedFlag(flag);
                        setNotes(flag.clinician_notes || '');
                      }}
                      className="px-4 py-1.5 bg-nh-green-deep hover:bg-nh-green-hover text-white text-xs font-semibold rounded-full transition-colors shadow-sm flex items-center gap-1"
                    >
                      Review Signal
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
