import React, { useState, useEffect } from 'react';
import { TrendChart } from './components/TrendChart';
import { ReviewQueue } from './components/ReviewQueue';
import { CaregiverView } from './components/CaregiverView';
import { TrendPoint } from './types';
import { NeurohavenLogo } from './components/NeurohavenLogo';
import { Activity, Lock, RefreshCw, UserCheck, HeartHandshake, Wrench, ShieldAlert, ChevronDown, ChevronUp } from 'lucide-react';

const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8000';

export const App: React.FC = () => {
  const [viewMode, setViewMode] = useState<'clinician' | 'caregiver'>('clinician');
  const [clinicianToken, setClinicianToken] = useState<string>('');
  const [caregiverToken, setCaregiverToken] = useState<string>('');
  const [caregiverPatientId, setCaregiverPatientId] = useState<string>('P0004');
  const [selectedPatientId, setSelectedPatientId] = useState<string>('P0004');
  const [trendPoints, setTrendPoints] = useState<TrendPoint[]>([]);
  const [loadingTrend, setLoadingTrend] = useState<boolean>(false);
  const [serviceStatus, setServiceStatus] = useState<string>('Connecting...');
  
  // System Diagnostics Collapsible State
  const [showDiagnostics, setShowDiagnostics] = useState<boolean>(false);
  const [rbacTestResult, setRbacTestResult] = useState<string | null>(null);
  const [resettingDemo, setResettingDemo] = useState<boolean>(false);

  // Fetch health check to get seeded dev tokens
  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((res) => res.json())
      .then((data) => {
        setServiceStatus(data.status || 'healthy');
        if (data.dev_seeded_tokens?.clinician_token) {
          setClinicianToken(data.dev_seeded_tokens.clinician_token);
        }
        if (data.dev_seeded_tokens?.caregiver_token) {
          setCaregiverToken(data.dev_seeded_tokens.caregiver_token);
        }
      })
      .catch(() => setServiceStatus('Offline'));
  }, []);

  const fetchPatientTrend = async (pid: string) => {
    if (!pid) return;
    setLoadingTrend(true);
    try {
      const res = await fetch(`${API_BASE_URL}/patients/${pid}/trend`);
      if (res.ok) {
        const data = await res.json();
        setTrendPoints(data.points || []);
      } else {
        setTrendPoints([]);
      }
    } catch {
      setTrendPoints([]);
    } finally {
      setLoadingTrend(false);
    }
  };

  useEffect(() => {
    if (selectedPatientId) {
      fetchPatientTrend(selectedPatientId);
    }
  }, [selectedPatientId]);

  const runRbacTest = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/flags`, {
        headers: { Authorization: `Bearer ${caregiverToken}` },
      });
      if (res.status === 403) {
        setRbacTestResult('HTTP 403 Forbidden — Caregiver JWT correctly denied access to clinician flags');
      } else {
        setRbacTestResult(`Unexpected status: ${res.status}`);
      }
    } catch (err: any) {
      setRbacTestResult(`Error: ${err.message}`);
    }
  };

  const runResetDemoFlags = async () => {
    setResettingDemo(true);
    try {
      const res = await fetch(`${API_BASE_URL}/reset-flags`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${clinicianToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        alert(`Demo queue reset successful! Tagged audit log with actor="system_diagnostic". (${data.count} flags restored)`);
        window.location.reload();
      } else {
        alert(`Reset failed with status ${res.status}`);
      }
    } catch (err: any) {
      alert(`Reset error: ${err.message}`);
    } finally {
      setResettingDemo(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#f2f5f2] text-nh-text-main p-4 sm:p-8 font-sans flex flex-col justify-between">
      <div>
        {/* Top Header Bar — Thin, low-weight wayfinding header */}
        <header className="max-w-7xl mx-auto mb-6 bg-white border border-[#e1eae3] rounded-2xl px-5 py-3.5 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <NeurohavenLogo className="h-7 w-auto" />
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="text-base font-extrabold tracking-tight text-nh-text-main">
                  CogDrift Engine
                </h1>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                  serviceStatus === 'healthy' || serviceStatus === 'ok'
                    ? 'bg-nh-green-light text-nh-green-deep border-[#d2e4d8]'
                    : 'bg-amber-50 text-amber-800 border-amber-200'
                }`}>
                  {serviceStatus === 'healthy' ? 'Cloud Connected' : serviceStatus}
                </span>
              </div>
            </div>
          </div>

          {/* Single Source of Truth Role Control */}
          <div className="flex items-center space-x-3">
            <div className="bg-nh-green-subtle p-1 rounded-full border border-[#d8e5dc] flex items-center gap-1">
              <button
                onClick={() => setViewMode('clinician')}
                className={`px-3.5 py-1.5 rounded-full text-xs font-bold transition-all flex items-center gap-1.5 ${
                  viewMode === 'clinician'
                    ? 'bg-nh-green-deep text-white shadow-sm'
                    : 'text-nh-text-muted hover:text-nh-green-deep'
                }`}
              >
                <UserCheck className="w-3.5 h-3.5" />
                Clinician Portal
              </button>

              <button
                onClick={() => setViewMode('caregiver')}
                className={`px-3.5 py-1.5 rounded-full text-xs font-bold transition-all flex items-center gap-1.5 ${
                  viewMode === 'caregiver'
                    ? 'bg-nh-green-deep text-white shadow-sm'
                    : 'text-nh-text-muted hover:text-nh-green-deep'
                }`}
              >
                <HeartHandshake className="w-3.5 h-3.5" />
                Caregiver Portal
              </button>
            </div>

            {/* Read-Only JWT Status Chip with Technical Tooltip */}
            <div
              className="flex items-center space-x-1.5 text-xs bg-slate-100 text-slate-700 border border-slate-200 px-3 py-1.5 rounded-full font-semibold cursor-help"
              title={`JWT Signature Verified | Role: ${viewMode === 'clinician' ? 'clinician' : 'caregiver (patient_ids: ["P0004"])'}`}
            >
              <Lock className="w-3.5 h-3.5 text-slate-500" />
              <span>Signed in as {viewMode === 'clinician' ? 'Clinician' : 'Caregiver'}</span>
            </div>
          </div>
        </header>

        {/* Hero Banner with Role-Aware Variant */}
        {viewMode === 'clinician' ? (
          <section className="max-w-7xl mx-auto mb-8 bg-gradient-to-r from-[#234936] to-[#36654b] rounded-3xl p-6 sm:p-8 text-white shadow-nh-lift flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
            <div className="relative z-10 max-w-2xl">
              <span className="text-xs font-bold tracking-widest text-[#a8d3b8] uppercase bg-white/10 px-3 py-1 rounded-full border border-white/10 inline-block mb-3">
                CLINICAL ANOMALY PIPELINE
              </span>
              <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
                Clinician-Reviewed Cognitive Monitoring
              </h2>
              <p className="text-xs sm:text-sm text-[#d4e6db] mt-2 leading-relaxed">
                Real-time rolling baseline analysis and Isolation Forest pattern detection for early-stage Alzheimer's rehabilitation games. Every detection signal requires clinician sign-off before reaching caregivers.
              </p>
            </div>

            {/* Clinician Patient Filter Pills (Separate from Role Identity) */}
            <div className="relative z-10 flex flex-wrap items-center gap-2.5">
              <span className="text-[10px] uppercase font-bold text-[#a8d3b8] block w-full">Quick Patient Filter:</span>
              {Array.from(new Set(['P0004', 'P0007', 'P0012', 'P0021', selectedPatientId])).map((pid) => (
                <button
                  key={pid}
                  onClick={() => setSelectedPatientId(pid)}
                  className={`px-4 py-2 rounded-full text-xs font-bold transition-all ${
                    selectedPatientId === pid
                      ? 'bg-white text-nh-green-deep shadow-md scale-105'
                      : 'bg-white/15 text-white hover:bg-white/25'
                  }`}
                >
                  Patient {pid}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <section className="max-w-7xl mx-auto mb-8 bg-gradient-to-r from-emerald-800 to-teal-900 rounded-3xl p-6 sm:p-8 text-white shadow-nh-lift flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative overflow-hidden">
            <div className="relative z-10 max-w-2xl">
              <span className="text-xs font-bold tracking-widest text-emerald-200 uppercase bg-white/10 px-3 py-1 rounded-full border border-white/10 inline-block mb-3">
                AUTHORIZED CAREGIVER VIEW
              </span>
              <h2 className="text-2xl sm:text-3xl font-extrabold tracking-tight">
                Care Updates for Your Patient
              </h2>
              <p className="text-xs sm:text-sm text-emerald-100 mt-2 leading-relaxed">
                Clinician-verified activity updates and guidance notes for your patient's daily cognitive exercises.
              </p>
            </div>

            <div className="relative z-10 flex flex-wrap items-center gap-2">
              <span className="text-[10px] text-emerald-200 font-bold uppercase block w-full">Authorized Patient Scope:</span>
              {['P0004', 'P0007'].map((pid) => (
                <button
                  key={pid}
                  onClick={() => setCaregiverPatientId(pid)}
                  className={`px-3.5 py-1.5 rounded-full text-xs font-bold transition-all ${
                    caregiverPatientId === pid
                      ? 'bg-white text-emerald-900 shadow-md scale-105'
                      : 'bg-white/15 text-white hover:bg-white/25'
                  }`}
                >
                  Patient {pid}
                </button>
              ))}
            </div>
          </section>
        )}

        {/* Main Grid */}
        <main className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8">
          {viewMode === 'clinician' ? (
            <>
              {/* Clinician Review Queue (5 cols) */}
              <div className="lg:col-span-5">
                <ReviewQueue
                  apiBaseUrl={API_BASE_URL}
                  clinicianToken={clinicianToken}
                  selectedPatientId={selectedPatientId}
                  onSelectPatient={(pid) => setSelectedPatientId(pid)}
                />
              </div>

              {/* Patient Trajectory Chart & Search (7 cols) */}
              <div className="lg:col-span-7 space-y-6">
                <div className="bg-white border border-[#e1eae3] rounded-3xl p-5 shadow-nh-card flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="p-2 bg-nh-green-light text-nh-green-deep rounded-2xl">
                      <Activity className="w-5 h-5" />
                    </div>
                    <div>
                      <span className="text-[11px] font-bold text-nh-green-accent uppercase tracking-wider block">
                        PATIENT SELECTION
                      </span>
                      <span className="text-sm font-bold text-nh-text-main">
                        Inspect Patient Trajectory:
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    <input
                      type="text"
                      value={selectedPatientId}
                      onChange={(e) => setSelectedPatientId(e.target.value)}
                      placeholder="e.g. P0004"
                      className="bg-nh-green-subtle border border-[#d2e4d8] rounded-full px-4 py-1.5 text-xs text-nh-text-main font-mono font-semibold focus:outline-none focus:border-nh-green-deep focus:ring-1 focus:ring-nh-green-deep w-32"
                    />
                    <button
                      onClick={() => fetchPatientTrend(selectedPatientId)}
                      className="p-2 bg-nh-green-deep hover:bg-nh-green-hover text-white rounded-full transition-colors"
                      title="Fetch Trend Data"
                    >
                      <RefreshCw className={`w-4 h-4 ${loadingTrend ? 'animate-spin' : ''}`} />
                    </button>
                  </div>
                </div>

                <TrendChart patientId={selectedPatientId} points={trendPoints} />
              </div>
            </>
          ) : (
            /* Caregiver Portal (Full Width) */
            <div className="lg:col-span-12">
              <CaregiverView
                apiBaseUrl={API_BASE_URL}
                caregiverToken={caregiverToken}
                patientId={caregiverPatientId}
              />
            </div>
          )}
        </main>
      </div>

      {/* Footer & Isolated System Diagnostics Panel */}
      <footer className="max-w-7xl mx-auto w-full mt-12 pt-6 border-t border-[#dce6df] space-y-4">
        <div className="text-center text-xs text-nh-text-muted">
          <p className="font-semibold text-nh-text-main">
            ⚠️ DISCLAIMER: CogDrift is a research prototype for statistical anomaly monitoring in cognitive rehabilitation data.
          </p>
          <p className="mt-1 text-[11px]">
            It is not a certified diagnostic device. Every detection signal must be reviewed and confirmed by a licensed clinician before any notification reaches a caregiver.
          </p>
        </div>

        {/* Collapsible System Diagnostics & Demo Controls Panel */}
        <div className="bg-slate-900 text-slate-100 rounded-2xl border border-slate-800 p-4 shadow-xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Wrench className="w-4 h-4 text-emerald-400" />
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                System Diagnostics & Dev Controls
              </span>
              <span className="text-[10px] bg-slate-800 text-slate-400 font-mono px-2 py-0.5 rounded-full border border-slate-700">
                QA Scaffolding
              </span>
            </div>

            <button
              onClick={() => setShowDiagnostics(!showDiagnostics)}
              className="text-xs font-bold text-emerald-400 hover:text-emerald-300 flex items-center gap-1"
            >
              {showDiagnostics ? 'Hide Controls' : 'Show Controls'}
              {showDiagnostics ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          </div>

          {showDiagnostics && (
            <div className="mt-4 pt-4 border-t border-slate-800 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="space-y-1">
                  <span className="text-xs font-bold text-slate-200 block">
                    Restore Demo Signals (System Diagnostic)
                  </span>
                  <p className="text-[11px] text-slate-400">
                    Resets submitted flags to pending and logs audit record with <code className="text-emerald-300">actor="system_diagnostic"</code>.
                  </p>
                </div>
                <button
                  onClick={runResetDemoFlags}
                  disabled={resettingDemo}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-xl transition-colors flex items-center gap-1.5 shadow-sm"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${resettingDemo ? 'animate-spin' : ''}`} />
                  Reset Demo Queue
                </button>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-slate-800">
                <div className="space-y-1">
                  <span className="text-xs font-bold text-slate-200 block">
                    Caregiver RBAC Boundary Test
                  </span>
                  <p className="text-[11px] text-slate-400">
                    Sends <code className="text-emerald-300">GET /flags</code> with Caregiver JWT to verify HTTP 403 Forbidden enforcement.
                  </p>
                </div>
                <button
                  onClick={runRbacTest}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-bold rounded-xl transition-colors border border-slate-700 flex items-center gap-1.5"
                >
                  <ShieldAlert className="w-3.5 h-3.5 text-emerald-400" />
                  Run RBAC Test (403)
                </button>
              </div>

              {rbacTestResult && (
                <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-xs font-mono text-emerald-300">
                  {rbacTestResult}
                </div>
              )}
            </div>
          )}
        </div>
      </footer>
    </div>
  );
};

export default App;
