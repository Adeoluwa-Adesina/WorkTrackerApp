import React, { useState, useEffect, createContext, useContext } from 'react';
import { createClient } from '@supabase/supabase-js';
// Corrected Shadcn UI imports based on typical installation
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
// Assuming Dialog, Input, Textarea are also installed via shadcn CLI
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';

import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';


// --- Supabase Context ---
const SupabaseContext = createContext(null);

// Export SupabaseProvider so it can be used in main.jsx/index.js
export const SupabaseProvider = ({ children }) => {
  const [supabase, setSupabase] = useState(null);
  const [isSupabaseReady, setIsSupabaseReady] = useState(false);

  useEffect(() => {
    const initializeSupabase = async () => {
      try {
        // Corrected for Vite: Use import.meta.env
        const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
        const supabaseKey = import.meta.env.VITE_SUPABASE_KEY;

        if (!supabaseUrl || !supabaseKey) {
          console.error("Supabase URL or Key not found in environment variables. Leaderboard will not function.");
          setIsSupabaseReady(true); // Mark as ready to allow app to render, even if not functional
          return;
        }

        const client = createClient(supabaseUrl, supabaseKey);
        setSupabase(client);
        setIsSupabaseReady(true);
        console.log("Supabase client initialized.");

      } catch (error) {
        console.error("Error initializing Supabase client:", error);
        setIsSupabaseReady(true);
      }
    };

    initializeSupabase();
  }, []);

  return (
    <SupabaseContext.Provider value={{ supabase, isSupabaseReady }}>
      {children}
    </SupabaseContext.Provider>
  );
};

// --- Custom Hook for Supabase Operations (Leaderboard specific) ---
const useSupabaseLeaderboard = () => {
  const { supabase, isSupabaseReady } = useContext(SupabaseContext);

  const fetchLeaderboardStats = async (dateFilter = 'today', sortBy = 'total_sessions') => {
    if (!supabase || !isSupabaseReady) {
      console.warn("Supabase client not ready or not initialized.");
      return [];
    }

    let queryBuilder = supabase.from('leaderboard_stats').select('*');

    // Date filtering
    const today = new Date();
    today.setHours(0, 0, 0, 0); // Start of today
    const todayISO = today.toISOString().split('T')[0];

    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const yesterdayISO = yesterday.toISOString().split('T')[0];

    console.log(`Fetching stats for dateFilter: ${dateFilter}, sortBy: ${sortBy}`);
    console.log(`Today ISO: ${todayISO}, Yesterday ISO: ${yesterdayISO}`);


    if (dateFilter === 'today') {
      queryBuilder = queryBuilder.eq('stat_date', todayISO);
    } else if (dateFilter === 'yesterday') {
      queryBuilder = queryBuilder.eq('stat_date', yesterdayISO);
    }
    // For 'all_time', no date filter is applied

    // Sorting
    if (sortBy === 'totalSessions') {
      queryBuilder = queryBuilder.order('total_sessions', { ascending: false });
    } else if (sortBy === 'longestSession') {
      queryBuilder = queryBuilder.order('longest_session_duration_minutes', { ascending: false });
    }
    // Add a secondary sort for consistent ordering if primary sort values are equal
    queryBuilder = queryBuilder.order('display_name', { ascending: true });


    try {
      const { data, error } = await queryBuilder;

      if (error) {
        console.error("Error fetching leaderboard stats:", error);
        return [];
      }
      console.log("Successfully fetched leaderboard data:", data);
      return data;
    } catch (e) {
      console.error("Supabase query error (caught):", e);
      return [];
    }
  };

  return { fetchLeaderboardStats };
};


// --- Leaderboard App Component ---
const App = () => {
  const { isSupabaseReady } = useContext(SupabaseContext);
  const { fetchLeaderboardStats } = useSupabaseLeaderboard();

  const [leaderboardData, setLeaderboardData] = useState([]);
  const [dateFilter, setDateFilter] = useState('today'); // 'today', 'yesterday', 'all_time'
  const [sortBy, setSortBy] = useState('totalSessions'); // 'totalSessions', 'longestSession'

  useEffect(() => {
    if (isSupabaseReady) {
      const loadData = async () => {
        console.log("Loading leaderboard data...");
        const data = await fetchLeaderboardStats(dateFilter, sortBy);
        setLeaderboardData(data);
        console.log("Leaderboard data set:", data);
      };
      loadData();
    }
  }, [isSupabaseReady, dateFilter, sortBy]); // Re-fetch when filters/sort change

  // Function to format duration for display
  const formatDuration = (minutes) => {
    if (typeof minutes !== 'number' || isNaN(minutes)) return 'N/A';
    const totalSeconds = Math.round(minutes * 60);
    const hours = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    const secs = totalSeconds % 60;
    
    let formatted = '';
    if (hours > 0) {
      formatted += `${hours}h `;
    }
    if (mins > 0 || hours > 0) {
      formatted += `${mins}m `;
    }
    formatted += `${secs}s`;
    
    return formatted.trim();
  };

  if (!isSupabaseReady) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-100">
        <p className="text-lg font-semibold text-gray-700">Loading leaderboard...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-100 flex flex-col items-center p-4 font-sans antialiased">
      <header className="w-full max-w-4xl bg-white shadow-md rounded-lg p-6 mb-6">
        <h1 className="text-3xl font-bold text-center text-gray-800 mb-4">Work Tracker Leaderboard</h1>

        <div className="flex flex-wrap justify-center gap-4 mb-6">
          <div>
            <label htmlFor="date-filter" className="block text-sm font-medium text-gray-700 mb-1">Date Filter:</label>
            <Select onValueChange={setDateFilter} value={dateFilter}>
              <SelectTrigger id="date-filter" className="w-[150px] rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm">
                <SelectValue placeholder="Today" />
              </SelectTrigger>
              <SelectContent className="bg-white border rounded-md shadow-lg">
                <SelectItem value="today">Today</SelectItem>
                <SelectItem value="yesterday">Yesterday</SelectItem>
                <SelectItem value="all_time">All Time</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label htmlFor="sort-by" className="block text-sm font-medium text-gray-700 mb-1">Sort By:</label>
            <Select onValueChange={setSortBy} value={sortBy}>
              <SelectTrigger id="sort-by" className="w-[180px] rounded-md border border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm">
                <SelectValue placeholder="Total Sessions" />
              </SelectTrigger>
              <SelectContent className="bg-white border rounded-md shadow-lg">
                <SelectItem value="totalSessions">Total Sessions</SelectItem>
                <SelectItem value="longestSession">Longest Session</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="overflow-x-auto rounded-md border border-gray-200 shadow-sm">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Rank</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Player</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Total Sessions</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Longest Session</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Last Synced</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {leaderboardData.length === 0 ? (
                <tr>
                  <td colSpan="6" className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-center">No leaderboard data available for this filter. Sync your stats from the desktop app!</td>
                </tr>
              ) : (
                leaderboardData.map((data, index) => (
                  <tr key={data.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{index + 1}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">{data.display_name}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{data.stat_date}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{data.total_sessions}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDuration(data.longest_session_duration_minutes)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {data.last_synced ? new Date(data.last_synced).toLocaleString() : 'N/A'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </header>
    </div>
  );
};

export default App;
