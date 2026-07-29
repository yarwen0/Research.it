"use client";
import React, { useEffect, useState, useRef } from "react";
import { Send, Paperclip, Zap, Clock, Turtle, ChevronDown } from "lucide-react";

export type SpeedMode = 'fast' | 'medium' | 'slow';

interface ChatInputProps {
  input: string;
  setInput: (value: string) => void;
  onSendMessage: () => void;
  isLoading: boolean;
  placeholder: string;
  variant?: 'default' | 'homepage-initial' | 'homepage-continued';
  className?: string;
  speedMode?: SpeedMode;
  onSpeedModeChange?: (mode: SpeedMode) => void;
}

const ChatInput: React.FC<ChatInputProps> = ({
  input,
  setInput,
  onSendMessage,
  isLoading,
  placeholder,
  variant = 'default',
  className = '',
  speedMode = 'fast',
  onSpeedModeChange,
}) => {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [textareaHeight, setTextareaHeight] = useState(36);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const speedModes: { value: SpeedMode; label: string; icon: React.ReactNode; description: string }[] = [
    { value: 'fast', label: 'Fast', icon: <Zap size={14} />, description: '2 topics, 2 papers' },
    { value: 'medium', label: 'Medium', icon: <Clock size={14} />, description: '5 topics, 5 papers' },
    { value: 'slow', label: 'Slow', icon: <Turtle size={14} />, description: '10 topics, 5 papers' },
  ];

  const currentMode = speedModes.find(mode => mode.value === speedMode) || speedModes[0];

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    
    // Auto-resize textarea
    const textarea = e.target;
    textarea.style.height = 'auto';
    const newHeight = Math.min(textarea.scrollHeight, 200);
    setTextareaHeight(newHeight);
    textarea.style.height = `${newHeight}px`;
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      if (input.trim() && !isLoading) {
        onSendMessage();
      }
    }
  };

  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      // Don't interfere if user is already typing in an input/textarea
      if (
        document.activeElement?.tagName === 'INPUT' ||
        document.activeElement?.tagName === 'TEXTAREA' ||
        (document.activeElement as HTMLElement)?.contentEditable === 'true'
      ) {
        return;
      }

      // Don't interfere with keyboard shortcuts (Ctrl, Cmd, Alt combinations)
      if (e.ctrlKey || e.metaKey || e.altKey) {
        return;
      }

      // Don't interfere with special keys
      if (
        e.key === 'Tab' ||
        e.key === 'Escape' ||
        e.key === 'Enter' ||
        e.key === 'ArrowUp' ||
        e.key === 'ArrowDown' ||
        e.key === 'ArrowLeft' ||
        e.key === 'ArrowRight' ||
        e.key === 'Backspace' ||
        e.key === 'Delete'
      ) {
        return;
      }

      // Only handle printable characters
      if (e.key.length === 1 && textareaRef.current && !isLoading) {
        // Prevent the default behavior to avoid duplicate characters
        e.preventDefault();
        
        // Focus the textarea
        textareaRef.current.focus();
        
        // Add the typed character to the input
        setInput(input + e.key);
      }
    };

    // Add event listener to document
    document.addEventListener('keypress', handleKeyPress);

    // Cleanup
    return () => {
      document.removeEventListener('keypress', handleKeyPress);
    };
  }, [textareaRef, isLoading, setInput, input]);

  const getContainerStyles = () => {
    const baseStyles = "w-full flex flex-col transition-all duration-200";
    
    switch (variant) {
      case 'homepage-initial':
        return `${baseStyles} gap-2 border rounded-lg bg-white dark:bg-gray-900 p-3 sm:p-4 shadow-lg border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600`;
      case 'homepage-continued':
        return `${baseStyles} gap-2 bg-white dark:bg-gray-900 p-3 sm:p-4 border border-gray-200 dark:border-gray-700 rounded-lg`;
      default:
        return `${baseStyles} gap-1.5 border rounded-lg bg-white dark:bg-gray-900 p-2 sm:p-3 shadow-lg border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600`;
    }
  };

  const getTextareaStyles = () => {
    const baseStyles = `flex-1 border-0 m-0 p-0 bg-transparent text-gray-900 dark:text-white
                       placeholder:text-gray-500 dark:placeholder:text-gray-400 focus-visible:ring-0 
                       focus-visible:ring-offset-0 focus:outline-none outline-none
                       resize-none overflow-y-auto
                       scrollbar-none [&::-webkit-resizer]:hidden transition-colors text-sm lg:text-md`;
    
    switch (variant) {
      case 'homepage-initial':
      case 'homepage-continued':
        return `${baseStyles} text-sm sm:text-base min-h-[36px] sm:min-h-[40px] max-h-[200px]`;
      default:
        return `${baseStyles} text-xs sm:text-sm min-h-[32px] sm:min-h-[36px] max-h-[200px]`;
    }
  };

  const getButtonSize = () => {
    switch (variant) {
      case 'homepage-initial':
      case 'homepage-continued':
        return { size: "icon" as const, className: "h-8 w-8 sm:h-10 sm:w-10 shrink-0" };
      default:
        return { size: "icon" as const, className: "h-7 w-7 sm:h-9 sm:w-9 shrink-0" };
    }
  };

  const getIconSize = () => {
    switch (variant) {
      case 'homepage-initial':
      case 'homepage-continued':
        return { imageIcon: 16, sendIcon: 14 }; 
      default:
        return { imageIcon: 14, sendIcon: 12 }; 
    }
  };

  const buttonConfig = getButtonSize();
  const iconSizes = getIconSize();

  return (
    <div className={`${getContainerStyles()} ${className}`}>
      <textarea
        ref={textareaRef}
        className={`${getTextareaStyles()} w-full`}
        style={{ 
          height: `${Math.max(
            variant === 'default' ? 32 : 36, 
            textareaHeight
          )}px` 
        }}
        placeholder={placeholder}
        value={input}
        onChange={handleTextareaChange}
        disabled={isLoading}
        onKeyDown={handleKeyDown}
        rows={1}
        aria-label="Research query"
      />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => {/* TODO: Implement file upload */}}
            className={`${buttonConfig.className} hover:bg-primary/50 text-gray-600 dark:text-gray-300 transition-colors rounded-md inline-flex items-center justify-center disabled:opacity-50`}
            disabled={isLoading}
            aria-label="Attach file (not yet available)"
          >
            <Paperclip size={iconSizes.imageIcon} />
          </button>
        </div>
        
        <div className="flex items-center gap-2">
          {/* Speed Mode Selector */}
          {onSpeedModeChange && (
            <div className="relative" ref={dropdownRef}>
              <button
                type="button"
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                disabled={isLoading}
                aria-label="Research speed mode"
                aria-haspopup="listbox"
                aria-expanded={isDropdownOpen}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
              >
                <span className="text-blue-600 dark:text-blue-400">{currentMode.icon}</span>
                <span className="font-medium">{currentMode.label}</span>
                <ChevronDown 
                  size={12} 
                  className={`transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} 
                />
              </button>

              {/* Dropdown Menu */}
              {isDropdownOpen && (
                <div className="absolute bottom-full right-0 mb-2 w-56 rounded-md shadow-lg bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 z-50 overflow-hidden">
                  {speedModes.map((mode) => (
                    <button
                      key={mode.value}
                      type="button"
                      onClick={() => {
                        onSpeedModeChange(mode.value);
                        setIsDropdownOpen(false);
                      }}
                      className={`w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors ${
                        speedMode === mode.value 
                          ? 'bg-blue-50 dark:bg-blue-900/20 border-l-2 border-blue-600' 
                          : ''
                      }`}
                    >
                      <span className={`${speedMode === mode.value ? 'text-blue-600 dark:text-blue-400' : 'text-gray-500 dark:text-gray-400'}`}>
                        {mode.icon}
                      </span>
                      <div className="flex-1">
                        <div className={`text-sm font-medium ${speedMode === mode.value ? 'text-blue-600 dark:text-blue-400' : 'text-gray-900 dark:text-gray-100'}`}>
                          {mode.label}
                        </div>
                        <div className="text-xs text-gray-500 dark:text-gray-400">
                          {mode.description}
                        </div>
                      </div>
                      {speedMode === mode.value && (
                        <svg className="w-4 h-4 text-blue-600 dark:text-blue-400" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          
          <button
            type="button"
            onClick={onSendMessage}
            disabled={isLoading || !input.trim()}
            className={`${buttonConfig.className} transition-all duration-200 disabled:opacity-50 bg-blue-600 text-white hover:bg-blue-700 rounded-md inline-flex items-center justify-center`}
            aria-label="Submit research"
          >
            <Send size={iconSizes.sendIcon} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ChatInput;
