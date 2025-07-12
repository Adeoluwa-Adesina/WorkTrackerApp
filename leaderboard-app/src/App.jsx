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

  const fetchLeaderboardStats = async (dateFilter = 'today', sortBy = 'total_duration_minutes') => { // Updated default sort
    if (!supabase || !isSupabaseReady) {
      console.warn("Supabase client not ready or not initialized.");
      return [];
    }

    let queryBuilder = supabase.from('leaderboard_stats').select('*');

    // Date filtering: Use a consistent 'today' based on a fixed timezone (e.g., WAT/UTC+1)
    // For web app, we'll calculate 'today' based on the same logic as Python app's sync.
    // This is crucial for consistency.
    const getTodayInWAT = () => {
      const now = new Date();
      // Get UTC milliseconds
      const utcMillis = now.getTime() + (now.getTimezoneOffset() * 60 * 1000);
      // Add 1 hour for WAT (UTC+1)
      const watMillis = utcMillis + (1 * 60 * 60 * 1000);
      const watDate = new Date(watMillis);
      // Format to YYYY-MM-DD
      return watDate.toISOString().split('T')[0];
    };

    const todayWATISO = getTodayInWAT();

    const yesterdayWAT = new Date(new Date(todayWATISO).getTime() - (24 * 60 * 60 * 1000));
    const yesterdayWATISO = yesterdayWAT.toISOString().split('T')[0];

    console.log(`Fetching stats for dateFilter: ${dateFilter}, sortBy: ${sortBy}`);
    console.log(`Today WAT ISO: ${todayWATISO}, Yesterday WAT ISO: ${yesterdayWATISO}`);


    if (dateFilter === 'today') {
      queryBuilder = queryBuilder.eq('stat_date', todayWATISO);
    } else if (dateFilter === 'yesterday') {
      queryBuilder = queryBuilder.eq('stat_date', yesterdayWATISO);
    }
    // For 'all_time', no date filter is applied, we fetch all records

    // Sorting
    if (sortBy === 'totalSessions') { // This now sorts by total_duration_minutes
      queryBuilder = queryBuilder.order('total_duration_minutes', { ascending: false });
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

  // New function to fetch online status
  const fetchOnlineStatus = async () => {
    if (!supabase || !isSupabaseReady) {
      console.warn("Supabase client not ready for online status fetch.");
      return [];
    }
    try {
      // Define online threshold (e.g., last 60 seconds)
      const onlineThreshold = new Date(new Date().getTime() - (60 * 1000)).toISOString(); // 60 seconds ago in ISO UTC
      
      // Fetch users active within the last 60 seconds
      const { data, error } = await supabase.from('online_status').select('*');

      if (error) {
        console.error("Error fetching online status:", error);
        return [];
      }

      const onlineUsers = data.filter(user => {
        return user.last_active_at && new Date(user.last_active_at).getTime() >= new Date(onlineThreshold).getTime();
      });
      
      console.log("Fetched online users:", onlineUsers);
      return onlineUsers.map(user => user.user_id); // Return just user_ids of online users

    } catch (e) {
      console.error("Supabase online status query error:", e);
      return [];
    }
  };


  return { fetchLeaderboardStats, fetchOnlineStatus };
};

// --- Helper function to aggregate user data ---
const aggregateData = (data) => {
    const userStats = new Map();

    data.forEach(stat => {
        if (userStats.has(stat.user_id)) {
            const existingStat = userStats.get(stat.user_id);
            existingStat.total_duration_minutes += stat.total_duration_minutes;
            existingStat.longest_session_duration_minutes = Math.max(
                existingStat.longest_session_duration_minutes,
                stat.longest_session_duration_minutes
            );
        } else {
            // Create a copy of the stat object to avoid mutation issues
            userStats.set(stat.user_id, { ...stat });
        }
    });

    return Array.from(userStats.values());
};


// --- Leaderboard App Component ---
const App = () => {
  const { isSupabaseReady } = useContext(SupabaseContext);
  const { fetchLeaderboardStats, fetchOnlineStatus } = useSupabaseLeaderboard();

  const [leaderboardData, setLeaderboardData] = useState([]);
  const [dateFilter, setDateFilter] = useState('today'); // 'today', 'yesterday', 'all_time'
  const [sortBy, setSortBy] = useState('totalSessions'); // 'totalSessions', 'longestSession'
  const [onlineUserIds, setOnlineUserIds] = useState([]); // New state for online user IDs

  // Effect to load leaderboard data
  useEffect(() => {
    if (isSupabaseReady) {
      const loadData = async () => {
        console.log("Loading leaderboard data...");
        // Fetch raw data without client-side sorting first
        const rawData = await fetchLeaderboardStats(dateFilter, sortBy);

        let processedData = rawData;

        // Aggregate data if the filter is 'all_time'
        if (dateFilter === 'all_time') {
          processedData = aggregateData(rawData);
        }

        // Sort the processed data (either raw or aggregated)
        processedData.sort((a, b) => {
            if (sortBy === 'totalSessions') {
                return b.total_duration_minutes - a.total_duration_minutes;
            } else if (sortBy === 'longestSession') {
                return b.longest_session_duration_minutes - a.longest_session_duration_minutes;
            }
            // Fallback sort by display name
            return a.display_name.localeCompare(b.display_name);
        });
        
        setLeaderboardData(processedData);
        console.log("Leaderboard data set:", processedData);
      };
      loadData();
    }
  }, [isSupabaseReady, dateFilter, sortBy]); // Re-fetch when filters/sort change

  // Effect to load online status periodically
  useEffect(() => {
    if (isSupabaseReady) {
      const loadOnlineStatus = async () => {
        const ids = await fetchOnlineStatus();
        setOnlineUserIds(ids);
      };
      
      // Load immediately and then every 30 seconds
      loadOnlineStatus();
      const intervalId = setInterval(loadOnlineStatus, 30000); // Refresh every 30 seconds

      return () => clearInterval(intervalId); // Cleanup interval on unmount
    }
  }, [isSupabaseReady]); // Only depends on isSupabaseReady

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

  // Function to format total duration specifically for display (e.g., 1h 30m)
  const formatTotalDuration = (minutes) => {
    if (typeof minutes !== 'number' || isNaN(minutes)) return 'N/A';
    const totalSeconds = Math.round(minutes * 60);
    const hours = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    
    let formatted = '';
    if (hours > 0) {
      formatted += `${hours}h `;
    }
    formatted += `${mins}m`;
    
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
                <SelectValue placeholder="Total Sessions" /> {/* This placeholder might be misleading now */}
              </SelectTrigger>
              <SelectContent className="bg-white border rounded-md shadow-lg">
                <SelectItem value="totalSessions">Total Duration</SelectItem> {/* Changed text */}
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
                {dateFilter !== 'all_time' && (
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Date</th>
                )}
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Total Duration</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Longest Session</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {leaderboardData.length === 0 ? (
                <tr>
                  <td colSpan={dateFilter !== 'all_time' ? 5 : 4} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 text-center">No leaderboard data available for this filter. Sync your stats from the desktop app!</td>
                </tr>
              ) : (
                leaderboardData.map((data, index) => (
                  <tr key={dateFilter === 'all_time' ? data.user_id : data.id}>
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{index + 1}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900 flex items-center">
                      {data.display_name}
                      {onlineUserIds.includes(data.user_id) && (
                        <span className="ml-2 h-2 w-2 bg-green-500 rounded-full animate-pulse" title="Online"></span>
                      )}
                    </td>
                    {dateFilter !== 'all_time' && (
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{data.stat_date}</td>
                    )}
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatTotalDuration(data.total_duration_minutes)}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{formatDuration(data.longest_session_duration_minutes)}</td>
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
