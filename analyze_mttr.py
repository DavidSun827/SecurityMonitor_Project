import os


def analyze_logs():
    if not os.path.exists("mttr_log.txt"):
        print("❌ mttr_log.txt not found. Please run the test first.")
        return

    t0 = t_detect = t_recovery = None
    tests = []

    with open("mttr_log.txt", "r") as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) != 2: continue

            event, timestamp = parts[0], float(parts[1])

            if event == "T0_CRASH":
                t0 = timestamp
            elif event == "T_DETECT":
                t_detect = timestamp
            elif event == "T_RECOVERY":
                t_recovery = timestamp
                if t0 and t_detect:
                    tests.append({
                        "detection_delay": t_detect - t0,
                        "total_ttr": t_recovery - t0
                    })
                    t0 = t_detect = t_recovery = None

    if not tests:
        print("⚠️ Log file is incomplete. No full crash-to-recovery cycle was found.")
        return

    print("\n📊 === Automated Reliability & Availability Report (Phase 3) ===")
    print(f"{'Test Run':<10} | {'Failure Detection Delay (s)':<28} | {'Total Recovery Time TTR (s)':<28}")
    print("-" * 55)

    total_ttr = 0
    for i, test in enumerate(tests):
        d_delay = round(test['detection_delay'], 3)
        ttr = round(test['total_ttr'], 3)
        total_ttr += ttr
        print(f"Test Run {i + 1:<2} | {d_delay:<20} | {ttr:<20}")

    mttr = round(total_ttr / len(tests), 3)
    print("-" * 55)
    print(f"📈 Measured MTTR (Mean Time To Recovery) = {mttr} s\n")

    # --- Interactive MTBF and System Availability calculation ---
    print("ℹ️  To compute System Availability, MTBF is required.")
    print("ℹ️  Approximately how many seconds did the system run stably before running the crash script?")
    user_input = input("👉 Enter stable runtime in seconds (e.g., 60 or 120): ")

    try:
        mtbf = float(user_input)
        # Availability formula: MTBF / (MTBF + MTTR)
        availability = (mtbf / (mtbf + mttr)) * 100

        print("\n" + "=" * 40)
        print("🎉 Final submission metrics (ready for report)")
        print("=" * 40)
        print(f"🔹 MTBF (Mean Time Between Failures): {mtbf} s")
        print(f"🔹 MTTR (Mean Time To Recovery)    : {mttr} s")
        print(f"🔹 System Availability : {availability:.4f}%")
        print("=" * 40)
        print("📝 Formula: Availability = MTBF / (MTBF + MTTR)")

    except ValueError:
        print("❌ Invalid input. Skipping availability calculation.")


if __name__ == "__main__":
    analyze_logs()