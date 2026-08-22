export default function format(results) {
  return JSON.stringify(
    results.map(({ filePath, messages }) => ({
      filePath,
      messages: messages.map(
        ({ ruleId, severity, fatal, message, line, column, endLine, endColumn }) => ({
          ruleId,
          severity,
          fatal,
          message,
          line,
          column,
          endLine,
          endColumn,
        }),
      ),
    })),
  );
}
