"use client";
import { Check, Clock, Infinity, Moon, Sun } from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { useEffect, useState } from "react";

const tiers = [
  {
    name: "Free",
    price: "Free",
    description: "Perfect for getting started",
    hoursSaved: "10",
    features: [
      "2 projects",
      "Basic research tools",
      "Research topic suggestions",
      "Community support",
      "Public knowledge graphs",
      "Limited AI access",
    ],
    highlighted: false,
  },
  {
    name: "Starter",
    price: "$20",
    period: "/month",
    description: "For serious researchers",
    hoursSaved: "50",
    features: [
      "10 projects",
      "Advanced research tools",
      "Priority support",
      "Latex Rendering",
      "Private knowledge graphs",
      "Full API access",
      "Export to PDF",
      "Custom citations",
    ],
    highlighted: true,
  },
  {
    name: "Researcher",
    price: "$50",
    period: "/month",
    description: "For professional teams",
    hoursSaved: "infinity",
    features: [
      "Unlimited projects",
      "All advanced features",
      "24/7 dedicated support",
      "Team collaboration",
      "Advanced analytics",
      "Custom integrations",
      "White-label options",
      "SLA guarantee",
    ],
    highlighted: false,
  },
];

export default function PricingPage() {
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
    <>
      {/* Simple Navigation Bar */}
      <nav className="fixed top-0 left-0 right-0 z-50 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <Link href="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
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

            {/* Right side actions */}
            <div className="flex items-center gap-6">
              <Link
                href="/"
                className="text-gray-700 dark:text-gray-300 hover:text-blue-600 dark:hover:text-blue-400 transition-colors font-medium"
              >
                Home
              </Link>

              {/* Dark Mode Toggle */}
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
        </div>
      </nav>

      <main className="min-h-screen pt-24 pb-16 px-4">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="text-center mb-16">
            <h1 className="text-4xl md:text-5xl font-bold text-gray-900 dark:text-white mb-4">
              Simple, Transparent Pricing
            </h1>
          </div>

          {/* Pricing Cards */}
          <div className="grid md:grid-cols-3 gap-8 max-w-6xl mx-auto">
            {tiers.map((tier) => (
              <div
                key={tier.name}
                className={`relative rounded-2xl border p-8 ${
                  tier.highlighted
                    ? "border-blue-500 dark:border-blue-400 shadow-2xl scale-105 bg-white dark:bg-gray-900"
                    : "border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950"
                } transition-all duration-300 hover:shadow-lg`}
              >
                {tier.highlighted && (
                  <div className="absolute -top-4 left-1/2 -translate-x-1/2 bg-blue-600 dark:bg-blue-500 text-white px-4 py-1 rounded-full text-sm font-semibold">
                    Most Popular
                  </div>
                )}

                <div className="text-center mb-8">
                  <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
                    {tier.name}
                  </h3>
                  <p className="text-gray-600 dark:text-gray-400 mb-4">
                    {tier.description}
                  </p>
                  <div className="flex items-baseline justify-center gap-1 mb-3">
                    <span className="text-5xl font-bold text-gray-900 dark:text-white">
                      {tier.price}
                    </span>
                    {tier.period && (
                      <span className="text-gray-600 dark:text-gray-400">
                        {tier.period}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center justify-center gap-2 text-blue-600 dark:text-blue-400 font-semibold">
                    <span>
                      {tier.hoursSaved === "infinity" ? (
                        <>
                          <Infinity className="w-5 h-5 inline" /> hours saved/week
                        </>
                      ) : (
                        `${tier.hoursSaved} hours saved/week`
                      )}
                    </span>
                  </div>
                </div>

                <ul className="space-y-4 mb-8">
                  {tier.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-3">
                      <Check className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
                      <span className="text-gray-700 dark:text-gray-300">
                        {feature}
                      </span>
                    </li>
                  ))}
                </ul>

                <button
                  className={`w-full py-3 px-6 rounded-lg font-semibold transition-all duration-200 ${
                    tier.highlighted
                      ? "bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 text-white shadow-lg hover:shadow-xl"
                      : "bg-gray-100 hover:bg-gray-200 dark:bg-gray-800 dark:hover:bg-gray-700 text-gray-900 dark:text-white"
                  }`}
                >
                  {tier.price === "Free" ? "Get Started" : "Subscribe Now"}
                </button>
              </div>
            ))}
          </div>

          {/* Additional Info */}
          <div className="mt-16 text-center">
            <p className="text-gray-600 dark:text-gray-400">
              All plans include access to our research platform and regular updates.
            </p>
            <p className="text-gray-600 dark:text-gray-400 mt-2">
              Need a custom plan?{" "}
              <a
                href="mailto:contact@research.it"
                className="text-blue-600 dark:text-blue-400 hover:underline"
              >
                Contact us
              </a>
            </p>
          </div>
        </div>
      </main>
    </>
  );
}
