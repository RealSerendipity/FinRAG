export type QuestionPanelProps = {
  label: string;
  askLabel: string;
  question: string;
  pending: boolean;
  statusText: string | null;
  onQuestionChange: (value: string) => void;
  onSubmit: () => void;
};

/** Render the controlled question form and request progress. */
export function QuestionPanel({
  label,
  askLabel,
  question,
  pending,
  statusText,
  onQuestionChange,
  onSubmit,
}: QuestionPanelProps) {
  return (
    <form
      className="question-panel"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      aria-busy={pending}
    >
      <label htmlFor="finrag-question">{label}</label>
      <input
        id="finrag-question"
        type="text"
        value={question}
        onChange={(event) => onQuestionChange(event.target.value)}
      />
      <button type="submit" disabled={pending}>
        {askLabel}
      </button>
      {statusText ? <p role="status">{statusText}</p> : null}
    </form>
  );
}
