import React, { useMemo, useState } from 'react';
import {
  ClarificationConstraints,
  ClarificationRequestPayload,
  ClarificationResponsePayload,
} from '@/types/data';

interface HumanFeedbackProps {
  websocket: WebSocket | null;
  onFeedbackSubmit?: (feedback: string | null) => void;
  questionForHuman?: boolean | string;
  clarificationRequest?: ClarificationRequestPayload | null;
  onClarificationSubmit?: (payload: ClarificationResponsePayload) => void;
}

const EMPTY_CONSTRAINTS: ClarificationConstraints = {
  scope: null,
  time_window: null,
  language: null,
  output_preference: null,
};

const MAX_SUBQUERIES = 10;

const HumanFeedback: React.FC<HumanFeedbackProps> = ({
  questionForHuman,
  onFeedbackSubmit,
  clarificationRequest,
  onClarificationSubmit,
}) => {
  const initialSubqueries = useMemo(
    () => clarificationRequest?.generated_subqueries?.slice(0, MAX_SUBQUERIES) || [],
    [clarificationRequest],
  );
  const [subqueries, setSubqueries] = useState<string[]>(initialSubqueries);
  const [notes, setNotes] = useState<string>('');
  const [constraints, setConstraints] = useState<ClarificationConstraints>(
    clarificationRequest?.defaults || EMPTY_CONSTRAINTS,
  );
  const [legacyFeedback, setLegacyFeedback] = useState<string>('');
  const [validationError, setValidationError] = useState<string>('');

  React.useEffect(() => {
    if (clarificationRequest) {
      setSubqueries(clarificationRequest.generated_subqueries?.slice(0, MAX_SUBQUERIES) || []);
      setConstraints(clarificationRequest.defaults || EMPTY_CONSTRAINTS);
      setNotes('');
      setValidationError('');
    }
  }, [clarificationRequest]);

  const updateSubquery = (index: number, value: string) => {
    const next = [...subqueries];
    next[index] = value;
    setSubqueries(next);
  };

  const addSubquery = () => {
    if (subqueries.length >= MAX_SUBQUERIES) {
      return;
    }
    setSubqueries([...subqueries, '']);
  };

  const removeSubquery = (index: number) => {
    setSubqueries(subqueries.filter((_, i) => i !== index));
  };

  const submitClarification = (e: React.FormEvent) => {
    e.preventDefault();
    if (!clarificationRequest || !onClarificationSubmit) {
      return;
    }
    const approvedSubqueries = Array.from(
      new Set(subqueries.map((item) => item.trim()).filter(Boolean)),
    );
    if (approvedSubqueries.length < 1) {
      setValidationError('At least one approved sub-question is required.');
      return;
    }
    if (approvedSubqueries.length > MAX_SUBQUERIES) {
      setValidationError(`No more than ${MAX_SUBQUERIES} sub-questions are allowed.`);
      return;
    }
    setValidationError('');
    onClarificationSubmit({
      request_id: clarificationRequest.request_id,
      approved_subqueries: approvedSubqueries,
      constraints,
      notes: notes.trim() || null,
    });
  };

  if (clarificationRequest) {
    return (
      <div className="bg-gray-900/95 border border-teal-600/40 p-4 rounded-lg shadow-xl mb-4">
        <h3 className="text-lg font-semibold mb-2 text-teal-200">Clarification Required</h3>
        <p className="mb-3 text-sm text-gray-300">
          Confirm or edit sub-questions before research continues.
        </p>
        <form onSubmit={submitClarification} className="space-y-4">
          <div>
            <p className="text-sm font-medium text-gray-200 mb-2">Clarification prompts</p>
            <ul className="list-disc pl-5 text-sm text-gray-300 space-y-1">
              {clarificationRequest.clarification_questions.map((q, idx) => (
                <li key={`${q}-${idx}`}>{q}</li>
              ))}
            </ul>
          </div>

          <div>
            <p className="text-sm font-medium text-gray-200 mb-2">
              Approved sub-questions ({subqueries.length}/{MAX_SUBQUERIES})
            </p>
            <div className="space-y-2">
              {subqueries.map((subquery, index) => (
                <div key={`subquery-${index}`} className="flex gap-2">
                  <input
                    className="w-full p-2 border border-gray-700 rounded-md bg-gray-800 text-gray-100"
                    value={subquery}
                    onChange={(event) => updateSubquery(index, event.target.value)}
                    placeholder={`Sub-question ${index + 1}`}
                  />
                  <button
                    type="button"
                    className="px-3 py-2 text-sm rounded-md bg-red-700/70 hover:bg-red-600 text-white"
                    onClick={() => removeSubquery(index)}
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              className="mt-2 px-3 py-2 text-sm rounded-md bg-gray-700 hover:bg-gray-600 text-white disabled:opacity-40"
              onClick={addSubquery}
              disabled={subqueries.length >= MAX_SUBQUERIES}
            >
              Add Sub-question
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <input
              className="w-full p-2 border border-gray-700 rounded-md bg-gray-800 text-gray-100"
              value={constraints.scope || ''}
              onChange={(event) => setConstraints({ ...constraints, scope: event.target.value || null })}
              placeholder="Scope/domains (comma separated)"
            />
            <input
              className="w-full p-2 border border-gray-700 rounded-md bg-gray-800 text-gray-100"
              value={constraints.time_window || ''}
              onChange={(event) => setConstraints({ ...constraints, time_window: event.target.value || null })}
              placeholder="Time window (e.g. 2024-2026)"
            />
            <input
              className="w-full p-2 border border-gray-700 rounded-md bg-gray-800 text-gray-100"
              value={constraints.language || ''}
              onChange={(event) => setConstraints({ ...constraints, language: event.target.value || null })}
              placeholder="Report language"
            />
            <input
              className="w-full p-2 border border-gray-700 rounded-md bg-gray-800 text-gray-100"
              value={constraints.output_preference || ''}
              onChange={(event) => setConstraints({ ...constraints, output_preference: event.target.value || null })}
              placeholder="Output preference"
            />
          </div>

          <textarea
            className="w-full p-2 border border-gray-700 rounded-md bg-gray-800 text-gray-100"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Additional notes (optional)"
          />

          {validationError && <p className="text-sm text-red-400">{validationError}</p>}

          <button
            type="submit"
            className="px-4 py-2 bg-teal-600 text-white rounded-md hover:bg-teal-500"
          >
            Confirm and Continue
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="bg-gray-100 p-4 rounded-lg shadow-md">
      <h3 className="text-lg font-semibold mb-2">Human Feedback Required</h3>
      <p className="mb-4">{typeof questionForHuman === 'string' ? questionForHuman : ''}</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (onFeedbackSubmit) {
            onFeedbackSubmit(legacyFeedback === '' ? null : legacyFeedback);
          }
          setLegacyFeedback('');
        }}
      >
        <textarea
          className="w-full p-2 border rounded-md"
          value={legacyFeedback}
          onChange={(e) => setLegacyFeedback(e.target.value)}
          placeholder="Enter your feedback here (or leave blank for 'no')"
        />
        <button
          type="submit"
          className="mt-2 px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600"
        >
          Submit Feedback
        </button>
      </form>
    </div>
  );
};

export default HumanFeedback;
