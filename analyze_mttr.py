import os


def analyze_logs():
    if not os.path.exists("mttr_log.txt"):
        print("❌ 找不到 mttr_log.txt，请先运行测试！")
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
        print("⚠️ 日志文件不完整，没有找到完整的宕机到恢复周期。")
        return

    print("\n📊 === 可靠性与可用性自动化分析报告 (Phase 3) ===")
    print(f"{'测试轮次':<10} | {'故障发现耗时 (s)':<20} | {'总恢复时间 (TTR) (s)':<20}")
    print("-" * 55)

    total_ttr = 0
    for i, test in enumerate(tests):
        d_delay = round(test['detection_delay'], 3)
        ttr = round(test['total_ttr'], 3)
        total_ttr += ttr
        print(f"Test Run {i + 1:<2} | {d_delay:<20} | {ttr:<20}")

    mttr = round(total_ttr / len(tests), 3)
    print("-" * 55)
    print(f"📈 测得 MTTR (平均恢复时间) = {mttr} 秒\n")

    # --- 新增：互动式 MTBF 与 可用性计算 ---
    print("ℹ️  为了计算系统可用性 (System Availability)，我们需要确认 MTBF。")
    print("ℹ️  在刚才的测试中，你大概让系统平稳运行了多少秒才执行暗杀脚本？")
    user_input = input("👉 请输入平稳运行时间 (例如 60 或 120): ")

    try:
        mtbf = float(user_input)
        # 可用性公式：MTBF / (MTBF + MTTR)
        availability = (mtbf / (mtbf + mttr)) * 100

        print("\n" + "=" * 40)
        print("🎉 最终交付指标 (请直接写入报告)")
        print("=" * 40)
        print(f"🔹 MTBF (平均无故障时间): {mtbf} 秒")
        print(f"🔹 MTTR (平均恢复时间)  : {mttr} 秒")
        print(f"🔹 System Availability : {availability:.4f}%")
        print("=" * 40)
        print("📝 公式说明: Availability = MTBF / (MTBF + MTTR)")

    except ValueError:
        print("❌ 输入无效，跳过可用性计算。")


if __name__ == "__main__":
    analyze_logs()