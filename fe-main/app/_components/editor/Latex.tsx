import React from 'react';
import Editor from '@monaco-editor/react';

const TabButton = ({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) => (
  <button
    onClick={onClick}
    className={`px-6 py-3 font-medium transition-colors ${
      active
        ? 'bg-white text-blue-600 border-b-2 border-blue-600'
        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
    }`}
  >
    {children}
  </button>
);

const LatexMonacoEditor = ({ value, onChange }: { value: string; onChange: (value: string | undefined) => void }) => (
  <div className="h-full">
    <Editor
      height="100%"
      defaultLanguage="latex"
      theme="vs"
      value={value}
      onChange={onChange}
      options={{
        minimap: { enabled: false },
        fontSize: 14,
        lineNumbers: 'on',
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
      }}
    />
  </div>
);

const LatexPreview = ({ pdfUrl, isCompiling, error }: { pdfUrl: string | null; isCompiling: boolean; error: string | null }) => {
  return (
    <div className="h-full overflow-auto bg-gray-100 flex items-center justify-center">
      {isCompiling ? (
        <div className="text-center">
          <div className="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
          <p className="text-gray-600">Compiling LaTeX...</p>
        </div>
      ) : error ? (
        <div className="text-red-600 p-6 bg-red-50 rounded-lg max-w-2xl mx-4">
          <strong className="text-lg block mb-2">Compilation Error:</strong>
          <p className="text-sm whitespace-pre-wrap">{error}</p>
        </div>
      ) : pdfUrl ? (
        <iframe
          src={pdfUrl}
          className="w-full h-full border-0"
          title="PDF Preview"
        />
      ) : (
        <div className="text-center text-gray-400">
          <p className="text-lg mb-2">No PDF preview available</p>
          <p className="text-sm">Click &quot;Compile&quot; to generate a PDF preview</p>
        </div>
      )}
    </div>
  );
};

export { LatexMonacoEditor, LatexPreview, TabButton };
