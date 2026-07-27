'use client';

import { Moon, Sun } from 'lucide-react';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { SidebarTrigger } from '@/components/ui/sidebar';

interface NavProps {
  title?: string;
}

export function Nav({ title }: NavProps) {
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    // Check initial theme
    const isDarkMode = document.documentElement.classList.contains('dark');
    setIsDark(isDarkMode);
  }, []);

  const toggleDarkMode = () => {
    const newIsDark = !isDark;
    setIsDark(newIsDark);
    
    if (newIsDark) {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    } else {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    }
  };

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950">
      <div className="flex items-center h-16 px-4 sm:px-6 lg:px-8">
        {/* Left: Sidebar trigger */}
        <div className="flex items-center">
          <SidebarTrigger className="text-gray-700 dark:text-gray-300" />
        </div>

        {/* Center: Logo or research title */}
        <div className="flex-1 flex items-center justify-center">
          {title ? (
            <h1 className="text-base font-semibold text-primary truncate text-center max-w-2xl px-4">
              {title}
            </h1>
          ) : (
            <Link href="/" className="flex items-center gap-2">
              <Image
                src="/logo.png"
                alt="research.it logo"
                width={32}
                height={32}
                className="w-8 h-8"
              />
              <span className="text-xl font-semibold text-gray-900 dark:text-white">
                Research<span className="text-blue-600 dark:text-blue-400">.it</span>
              </span>
            </Link>
          )}
        </div>

        {/* Right: Links */}
        <div className="flex items-center gap-6">
          <Link
            href="/editor"
            className="text-gray-700 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors font-medium"
          >
            Editor
          </Link>
          <Link
            href="/pricing"
            className="text-gray-700 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors font-medium"
          >
            Pricing
          </Link>

          <button
            onClick={toggleDarkMode}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            aria-label="Toggle dark mode"
          >
            {isDark ? (
              <Sun className="w-5 h-5 text-gray-700 dark:text-gray-300" />
            ) : (
              <Moon className="w-5 h-5 text-gray-700 dark:text-gray-300" />
            )}
          </button>
        </div>
      </div>
    </nav>
  );
}
