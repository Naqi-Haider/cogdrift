import React, { useState, useMemo } from 'react';
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Dot,
  Scatter,
} from 'recharts';
import { TrendPoint, AnomalyMarker } from '../types';
import { Calendar, Eye, EyeOff, AlertCircle, Activity, ShieldAlert } from 'lucide-react';

interface TrendChartProps {
  patientId: string;
  points: TrendPoint[];
  anomalies?: AnomalyMarker[];
  onSelectDate?: (date: string) => void;
}

export const TrendChart: React.FC<TrendChartProps> = ({
  patientId,
  points,
  anomalies = [],
  onSelectDate,
}) => {
  // Filter States
  const [rangeFilter, setRangeFilter] = useState<'30D' | '60D' | 'ALL' | 'CUSTOM'>('30D');
  const [startDate, setStartDate] = useState<string>('');
  const [endDate, setEndDate] = useState<string>('');

  // Series Visibility Toggles
  const [showDailyScore, setShowDailyScore] = useState<boolean>(true);
  const [showRollingMean, setShowRollingMean] = useState<boolean>(true);
  const [showBaselineBand, setShowBaselineBand] = useState<boolean>(true);
  const [showAnomalies, setShowAnomalies] = useState<boolean>(true);

  // Filter Points by Selected Time Horizon / Date Range
  const filteredPoints = useMemo(() => {
    if (!points || points.length === 0) return [];

    let sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));

    if (rangeFilter === '30D') {
      sorted = sorted.slice(-30);
    } else if (rangeFilter === '60D') {
      sorted = sorted.slice(-60);
    } else if (rangeFilter === 'CUSTOM') {
      if (startDate) sorted = sorted.filter((p) => p.date >= startDate);
      if (endDate) sorted = sorted.filter((p) => p.date <= endDate);
    }

    return sorted;
  }, [points, rangeFilter, startDate, endDate]);

  const minDateInHorizon = filteredPoints.length > 0 ? filteredPoints[0].date : '';
  const maxDateInHorizon = filteredPoints.length > 0 ? filteredPoints[filteredPoints.length - 1].date : '';

  // Filter anomalies within active time horizon (Section 15 Item 13)
  const filteredAnomalies = useMemo(() => {
    if (!anomalies || anomalies.length === 0) return [];
    return anomalies.filter(
      (a) => a.date >= minDateInHorizon && a.date <= maxDateInHorizon
    );
  }, [anomalies, minDateInHorizon, maxDateInHorizon]);

  const latestPoint = filteredPoints.length > 0 ? filteredPoints[filteredPoints.length - 1] : null;

  const chartData = useMemo(() => {
    const anomalyMap = new Map<string, AnomalyMarker>();
    filteredAnomalies.forEach((a) => anomalyMap.set(a.date, a));

    return filteredPoints.map((p) => {
      const mean = p.rolling_mean ?? p.daily_cognitive_score;
      const std = p.rolling_std ?? 0.5;
      const upper = p.upper_bound ?? Math.min(10, mean + 2 * std);
      const lower = p.lower_bound ?? Math.max(0, mean - 2 * std);
      const anomalyInfo = anomalyMap.get(p.date);

      return {
        date: p.date,
        score: round1(p.daily_cognitive_score),
        rolling_mean: round1(mean),
        upper_bound: round1(upper),
        lower_bound: round1(lower),
        band: [round1(lower), round1(upper)],
        z_score: p.z_score !== undefined && p.z_score !== null ? round1(p.z_score) : null,
        is_anomaly: p.is_anomaly || !!anomalyInfo,
        anomaly_status: anomalyInfo?.status || (p.is_anomaly ? 'pending' : null),
        anomaly_detector: anomalyInfo?.detector_type || 'TREND',
      };
    });
  }, [filteredPoints, filteredAnomalies]);

  function round1(val: number) {
    return Math.round(val * 100) / 100;
  }

  // High-Contrast Tooltip with Status-Aware Anomaly Details
  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      const data = payload[0].payload;
      return (
        <div className="bg-white border border-[#cbe0d3] p-3.5 rounded-2xl shadow-nh-lift text-xs text-nh-text-main space-y-1.5 min-w-[220px]">
          <div className="font-bold text-nh-green-deep border-b border-[#edf3ee] pb-1.5 flex justify-between items-center">
            <span>Date: {label}</span>
            {data.is_anomaly && (
              <span
                className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase ${
                  data.anomaly_status === 'confirmed'
                    ? 'bg-red-100 text-red-800 border-red-200'
                    : data.anomaly_status === 'dismissed'
                    ? 'bg-slate-100 text-slate-700 border-slate-200'
                    : 'bg-amber-100 text-amber-900 border-amber-200'
                }`}
              >
                {data.anomaly_status || 'PENDING'}
              </span>
            )}
          </div>

          <div className="flex justify-between items-center pt-0.5">
            <span className="text-nh-text-muted font-medium">Daily Score:</span>
            <span className="font-bold text-nh-green-deep text-sm">{data.score} / 10</span>
          </div>

          <div className="flex justify-between items-center">
            <span className="text-nh-text-muted font-medium">Rolling Mean:</span>
            <span className="font-semibold text-nh-green-accent">{data.rolling_mean}</span>
          </div>

          <div className="flex justify-between items-center">
            <span className="text-nh-text-muted font-medium">Baseline (±2σ):</span>
            <span className="font-semibold text-nh-text-main">{data.lower_bound} - {data.upper_bound}</span>
          </div>

          {data.is_anomaly && (
            <div className="pt-1.5 border-t border-[#edf3ee] space-y-1">
              <div className="flex justify-between items-center">
                <span className="text-nh-text-muted font-medium">Detector:</span>
                <span className="font-bold text-nh-green-deep">{data.anomaly_detector}</span>
              </div>
              {data.z_score !== null && (
                <div className="flex justify-between items-center">
                  <span className="text-nh-text-muted font-medium">Z-Score:</span>
                  <span className={`font-bold ${data.z_score < -2.0 ? 'text-red-600' : 'text-nh-text-main'}`}>
                    {data.z_score}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-4">
      {/* Bento Grid Header Controls */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Bento 1: Time Horizon Selection */}
        <div className="bg-white border border-[#e1eae3] rounded-2xl p-4 shadow-nh-card flex flex-col justify-between">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-bold text-nh-green-accent uppercase tracking-wider flex items-center gap-1.5">
              <Calendar className="w-3.5 h-3.5 text-nh-green-deep" />
              Time Horizon
            </span>
            <span className="text-[11px] font-mono text-nh-text-muted font-semibold">
              {filteredPoints.length} Days
            </span>
          </div>

          <div className="grid grid-cols-3 gap-1 bg-nh-green-subtle p-1 rounded-xl border border-[#d8e5dc]">
            <button
              onClick={() => setRangeFilter('30D')}
              className={`py-1.5 rounded-lg text-xs font-bold transition-all text-center ${
                rangeFilter === '30D'
                  ? 'bg-nh-green-deep text-white shadow-sm'
                  : 'text-nh-text-muted hover:text-nh-green-deep'
              }`}
            >
              30D
            </button>
            <button
              onClick={() => setRangeFilter('60D')}
              className={`py-1.5 rounded-lg text-xs font-bold transition-all text-center ${
                rangeFilter === '60D'
                  ? 'bg-nh-green-deep text-white shadow-sm'
                  : 'text-nh-text-muted hover:text-nh-green-deep'
              }`}
            >
              60D
            </button>
            <button
              onClick={() => setRangeFilter('CUSTOM')}
              className={`py-1.5 rounded-lg text-xs font-bold transition-all text-center ${
                rangeFilter === 'CUSTOM'
                  ? 'bg-nh-green-deep text-white shadow-sm'
                  : 'text-nh-text-muted hover:text-nh-green-deep'
              }`}
            >
              Custom
            </button>
          </div>
        </div>

        {/* Bento 2: Data Layers Visibility */}
        <div className="bg-white border border-[#e1eae3] rounded-2xl p-4 shadow-nh-card flex flex-col justify-between">
          <span className="text-[11px] font-bold text-nh-green-accent uppercase tracking-wider block mb-2">
            Layer Controls
          </span>
          <div className="flex flex-wrap gap-1.5">
            <button
              onClick={() => setShowDailyScore(!showDailyScore)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1 border transition-all ${
                showDailyScore
                  ? 'bg-nh-green-deep text-white border-nh-green-deep'
                  : 'bg-nh-green-subtle text-nh-text-muted border-[#d8e5dc]'
              }`}
            >
              {showDailyScore ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
              Daily
            </button>
            <button
              onClick={() => setShowRollingMean(!showRollingMean)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1 border transition-all ${
                showRollingMean
                  ? 'bg-nh-green-accent text-white border-nh-green-accent'
                  : 'bg-nh-green-subtle text-nh-text-muted border-[#d8e5dc]'
              }`}
            >
              {showRollingMean ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
              Mean
            </button>
            <button
              onClick={() => setShowBaselineBand(!showBaselineBand)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1 border transition-all ${
                showBaselineBand
                  ? 'bg-emerald-100 text-nh-green-deep border-emerald-300'
                  : 'bg-nh-green-subtle text-nh-text-muted border-[#d8e5dc]'
              }`}
            >
              {showBaselineBand ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
              Band
            </button>
            <button
              onClick={() => setShowAnomalies(!showAnomalies)}
              className={`px-2.5 py-1 rounded-lg text-xs font-semibold flex items-center gap-1 border transition-all ${
                showAnomalies
                  ? 'bg-red-600 text-white border-red-600'
                  : 'bg-red-50 text-red-700 border-red-200'
              }`}
            >
              <AlertCircle className="w-3 h-3" />
              Anomalies
            </button>
          </div>
        </div>

        {/* Bento 3: Elevated Current Score Metric Card (P2 Item 14) */}
        <div className="bg-white border border-[#e1eae3] rounded-2xl p-4 shadow-nh-card flex items-center justify-between">
          <div>
            <span className="text-[11px] font-bold text-nh-text-muted uppercase tracking-wider block">
              Patient {patientId} Score
            </span>
            <div className="flex items-baseline space-x-2 mt-1">
              <span className="text-3xl font-black text-nh-green-deep tracking-tight">
                {latestPoint ? latestPoint.daily_cognitive_score : '--'}
              </span>
              <span className="text-xs text-nh-text-muted font-bold">/ 10.0 Daily</span>
            </div>
          </div>
          <div className="p-3.5 bg-nh-green-light rounded-2xl text-nh-green-deep">
            <Activity className="w-7 h-7" />
          </div>
        </div>
      </div>

      {/* Custom Date Range Picker Bar */}
      {rangeFilter === 'CUSTOM' && (
        <div className="p-3 bg-white border border-[#e1eae3] rounded-2xl flex flex-wrap items-center gap-3 text-xs shadow-sm">
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-nh-text-muted">Start:</span>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="bg-nh-green-subtle border border-[#d8e5dc] rounded-lg px-2.5 py-1 text-xs font-mono text-nh-text-main focus:outline-none"
            />
          </div>
          <div className="flex items-center space-x-2">
            <span className="font-semibold text-nh-text-muted">End:</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="bg-nh-green-subtle border border-[#d8e5dc] rounded-lg px-2.5 py-1 text-xs font-mono text-nh-text-main focus:outline-none"
            />
          </div>
          {(startDate || endDate) && (
            <button
              onClick={() => {
                setStartDate('');
                setEndDate('');
              }}
              className="text-xs text-nh-green-deep hover:underline font-semibold"
            >
              Reset
            </button>
          )}
        </div>
      )}

      {/* Main Graph Card */}
      <div className="bg-white border border-[#e1eae3] rounded-3xl p-6 shadow-nh-card">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4">
          <div>
            <h3 className="text-lg font-bold text-nh-text-main">
              Cognitive Baseline & Trajectory Chart
            </h3>
            <p className="text-xs text-nh-text-muted">
              Server-computed 30-day rolling baseline (±2σ confidence band) with status-styled anomaly markers
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* Status Legend for Anomalies (Section 15 Item 13) */}
            <div className="flex items-center space-x-2 text-[10px] bg-slate-50 border border-slate-200 px-2.5 py-1 rounded-full font-mono shadow-xs">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-600"></span>Confirmed</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber-500"></span>Pending</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full border border-slate-400 bg-white"></span>Dismissed</span>
            </div>

            <span className="text-xs font-mono px-3 py-1 bg-nh-green-subtle text-nh-green-deep border border-[#d8e5dc] rounded-full font-bold">
              {chartData.length} Days Rendered
            </span>
          </div>
        </div>

        {chartData.length === 0 ? (
          <div className="h-72 flex flex-col items-center justify-center text-nh-text-muted text-sm bg-nh-green-subtle/40 rounded-2xl border border-dashed border-[#d8e5dc] p-6">
            <span className="font-semibold text-nh-text-main text-base mb-1">No Data Points Available</span>
            <p className="text-xs text-nh-text-muted text-center max-w-sm">
              Adjust your time horizon or date range filters above.
            </p>
          </div>
        ) : (
          <div className="h-72 w-full pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 10, right: 15, left: -20, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e8efe9" vertical={false} />
                <XAxis
                  dataKey="date"
                  stroke="#8fa095"
                  tick={{ fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={30}
                  interval="preserveStartEnd"
                />
                <YAxis domain={[0, 10]} stroke="#8fa095" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />

                <Tooltip content={<CustomTooltip />} />

                {/* Shaded Confidence Band */}
                {showBaselineBand && (
                  <Area
                    type="monotone"
                    dataKey="band"
                    stroke="#52796f"
                    strokeDasharray="3 3"
                    strokeWidth={1}
                    fill="#52796f"
                    fillOpacity={0.12}
                    name="Baseline Band (±2σ)"
                  />
                )}

                {/* Rolling Mean Line */}
                {showRollingMean && (
                  <Line
                    type="monotone"
                    dataKey="rolling_mean"
                    stroke="#52796f"
                    strokeWidth={2}
                    strokeDasharray="4 4"
                    dot={false}
                    name="Rolling Mean"
                  />
                )}

                {/* Daily Score Line */}
                {showDailyScore && (
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#234936"
                    strokeWidth={3}
                    name="Daily Score"
                    dot={(props: any) => {
                      const { cx, cy, payload } = props;
                      if (showAnomalies && payload.is_anomaly) {
                        // Status-styled anomaly dots per Section 15 Item 13:
                        // - Confirmed: filled red (#dc2626)
                        // - Pending: amber (#d97706)
                        // - Dismissed: hollow gray (#94a3b8)
                        const status = payload.anomaly_status;
                        const fill =
                          status === 'confirmed'
                            ? '#dc2626'
                            : status === 'dismissed'
                            ? '#ffffff'
                            : '#d97706';
                        const stroke =
                          status === 'dismissed' ? '#94a3b8' : fill;

                        return (
                          <circle
                            key={props.index}
                            cx={cx}
                            cy={cy}
                            r={6}
                            fill={fill}
                            stroke={stroke}
                            strokeWidth={2}
                            className="cursor-pointer transition-transform hover:scale-125"
                            onClick={() => onSelectDate && onSelectDate(payload.date)}
                          />
                        );
                      }
                      return <Dot key={props.index} cx={cx} cy={cy} r={3} fill="#234936" />;
                    }}
                  />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Static, Non-Clickable Disclaimer Warning Strip (P2 Item 14) */}
        <div className="mt-4 pt-4 border-t border-[#edf3ee] flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
          <span className="text-xs text-nh-text-muted">30-Day Rolling Baseline • Statistical signal monitoring</span>
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-2 text-[11px] text-amber-900 font-medium flex items-center gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-700 flex-shrink-0" />
            <span>Statistical signal for clinician review — not a clinical diagnosis</span>
          </div>
        </div>
      </div>
    </div>
  );
};
