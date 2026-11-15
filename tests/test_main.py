import math, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import main as hl


V = hl.kmh_to_mps(1200.0)


# --- tube aerodynamics
def test_kmh_mps_roundtrip(): assert abs(hl.mps_to_kmh(hl.kmh_to_mps(1200.0)) - 1200.0) < 1e-9
def test_density_atm(): assert 1.19 < hl.air_density(hl.P_ATM_PA) < 1.22
def test_density_scales_with_pressure():
    assert abs(hl.air_density(hl.P_ATM_PA) / hl.air_density(hl.P_TUBE_PA)
               - hl.P_ATM_PA / hl.P_TUBE_PA) < 1e-6
def test_density_rejects_bad_input():
    try:
        hl.air_density(0.0); assert False
    except ValueError: pass
def test_sound_speed_formula():
    assert abs(hl.speed_of_sound() - math.sqrt(hl.GAMMA * hl.R_GAS * hl.T_TUBE_K)) < 1e-9
def test_drag_ratio_equals_density_ratio():
    assert abs(hl.aero_drag_force(V, hl.P_ATM_PA) / hl.aero_drag_force(V, hl.P_TUBE_PA)
               - hl.P_ATM_PA / hl.P_TUBE_PA) < 1e-4
def test_drag_quadratic_in_speed():
    assert abs(hl.aero_drag_force(100.0) / hl.aero_drag_force(50.0) - 4.0) < 1e-9
def test_drag_power_ratio_over_1000():
    assert hl.aero_drag_power_kw(V, hl.P_ATM_PA) / hl.aero_drag_power_kw(V, hl.P_TUBE_PA) > 1000.0
def test_blockage_is_036(): assert abs(hl.BLOCKAGE - 0.36) < 1e-12
def test_area_mach_at_mach1(): assert abs(hl.area_mach_ratio(1.0) - 1.0) < 1e-12
def test_area_mach_rejects_supersonic():
    try:
        hl.area_mach_ratio(1.5); assert False
    except ValueError: pass
def test_kantrowitz_solves_area_relation():
    mk = hl.kantrowitz_mach()
    assert abs(hl.area_mach_ratio(mk) - 1.0 / (1.0 - hl.BLOCKAGE)) < 0.01
def test_kantrowitz_falls_with_blockage():
    assert hl.kantrowitz_mach(0.20) > hl.kantrowitz_mach(0.36) > hl.kantrowitz_mach(0.50)
def test_cruise_above_kantrowitz(): assert V > hl.kantrowitz_speed_mps()
def test_bypass_required(): assert hl.aero_report()["bypass_required_at_cruise"] is True
def test_bypass_mass_flow_formula():
    assert abs(hl.bypass_mass_flow(V) - hl.air_density(hl.P_TUBE_PA) * V * hl.POD_AREA_M2) < 1e-9
def test_bypass_power_positive(): assert hl.bypass_power_kw(V) > 0

# --- levitation (MagLevX carry-over)
def test_eds_zero_at_standstill(): assert hl.eds_lift(0.0) == 0.0
def test_eds_k_scaled_by_bogies(): assert abs(hl.EDS_K - hl.EDS_K_TRAINSET * 0.25) < 1e-6
def test_eds_lift_rises(): assert hl.eds_lift(100.0) > hl.eds_lift(20.0) > 0
def test_eds_liftoff_balances_weight():
    v = hl.eds_liftoff_speed()
    assert v > 0 and abs(hl.eds_lift(v) - hl.POD["mass_kg"] * hl.G) < 50.0
def test_eds_drag_rest(): assert hl.eds_magnetic_drag(0.0) == 0.0
def test_eds_drag_peak(): assert abs(hl.eds_magnetic_drag(hl.EDS_DRAG_VPEAK) - hl.EDS_DRAG_PEAK_N) < 1e-6
def test_eds_drag_falls(): assert hl.eds_magnetic_drag(V) < hl.EDS_DRAG_PEAK_N
def test_levitation_power_peaks_early(): assert hl.levitation_power_kw(30.0) > hl.levitation_power_kw(V)
def test_levitation_gate(): assert hl.levitation_report()["gate"] == "HOLD"

# --- propulsion + trip
def test_accel_time(): assert abs(hl.accel_time_to_speed(V) - V / hl.A_MAX) < 1e-12
def test_accel_distance(): assert abs(hl.accel_distance(V) - V ** 2 / (2 * hl.A_MAX)) < 1e-9
def test_comfort_clamp():
    assert hl.comfort_clamp(2.5) == hl.A_MAX and hl.comfort_clamp(-2.5) == -hl.A_MAX
    assert hl.comfort_clamp(0.3) == 0.3
def test_comfort_ceiling(): assert hl.A_MAX / hl.G < hl.G_LIMIT
def test_thrust_exceeds_drags():
    assert hl.thrust_for_accel(hl.POD["mass_kg"], hl.A_MAX, V) > hl.aero_drag_force(V) + hl.eds_magnetic_drag(V)
def test_profile_reaches_cruise():
    p = hl.trip_profile()
    assert abs(p["top_speed_kmh"] - 1200.0) < 1.0
def test_profile_covers_route():
    p = hl.trip_profile()
    assert abs(p["distance_m"] - hl.ROUTE_LA_SF_M) < 500.0
def test_profile_time_band():
    p = hl.trip_profile()
    assert 1700.0 < p["travel_time_s"] < 2600.0
def test_profile_peak_g_within_comfort():
    p = hl.trip_profile()
    assert p["peak_g"] <= hl.G_LIMIT
def test_trip_energy_positive(): assert hl.trip_profile()["trip_energy_kwh"] > 0
def test_energy_below_air_estimate():
    ec = hl.energy_comparison()
    assert 0 < ec["hyperloop_lev_model"] < ec["short_haul_air_est"]
def test_trip_faster_than_flight_block():
    assert hl.trip_profile()["travel_time_min"] < hl.FLIGHT_LA_SF_BLOCK_MIN
def test_phases_trapezoidal():
    ph = hl.trip_phases()
    assert ph["profile"] == "trapezoidal"
    assert abs(ph["accel_distance_km"] - hl.accel_distance(V) / 1000.0) < 0.01
def test_phases_triangular_short_route():
    ph = hl.trip_phases(distance_m=50000.0)
    assert ph["profile"].startswith("triangular")
    assert abs(ph["peak_speed_kmh"] - hl.mps_to_kmh(math.sqrt(hl.A_MAX * 50000.0))) < 0.2

# --- pressure systems
def test_tube_air_mass_formula():
    expect = hl.air_density(hl.P_TUBE_PA) * hl.TUBE_AREA_M2 * hl.ROUTE_LA_SF_M
    assert abs(hl.tube_air_mass_kg() - expect) < 1e-6
def test_tube_air_mass_ratio():
    assert abs(hl.tube_air_mass_kg(pressure_pa=hl.P_ATM_PA) / hl.tube_air_mass_kg()
               - hl.P_ATM_PA / hl.P_TUBE_PA) < 1e-4
def test_pump_power_formula():
    expect = hl.LEAK_LOAD_PA_M3_S * math.log(hl.P_ATM_PA / hl.P_TUBE_PA) / hl.PUMP_EFFICIENCY / 1000.0
    assert abs(hl.pump_power_kw() - expect) < 1e-9
def test_pump_power_rises_as_pressure_drops(): assert hl.pump_power_kw(50.0) > hl.pump_power_kw(100.0)
def test_section_count_covers_route():
    assert hl.SECTION_COUNT * hl.TUBE["section_km"] * 1000.0 >= hl.ROUTE_LA_SF_M
def test_choked_flow_formula():
    expect = (hl.BREACH_CD * hl.BREACH_AREA_M2 * hl.P_ATM_PA
              * math.sqrt(hl.GAMMA / (hl.R_GAS * hl.T_TUBE_K)) * (1.2) ** -3.0)
    assert abs(hl.choked_mass_flow_kg_s() - expect) < 1e-9
def test_repressurise_time_positive(): assert hl.repressurise_time_s() > 0
def test_breathing_reserve_formula():
    expect = hl.O2_RESERVE_KG / (hl.POD["seats"] * hl.O2_USE_KG_PER_PAX_HOUR)
    assert abs(hl.breathing_reserve_hours() - expect) < 1e-9
def test_reserve_outlasts_repressurisation(): assert hl.pressure_report()["reserve_margin_x"] > 1.0
def test_pressure_gate(): assert hl.pressure_report()["gate"] == "HOLD"

# --- braking + spacing
def test_braking_service_formula():
    assert abs(hl.braking_distance(V, hl.SERVICE_DECEL) - V ** 2 / (2 * hl.SERVICE_DECEL)) < 1e-9
def test_braking_eddy_shorter(): assert hl.braking_distance(V, hl.EDDY_DECEL) < hl.braking_distance(V, hl.SERVICE_DECEL)
def test_braking_skid_longest(): assert hl.braking_distance(V, hl.SKID_DECEL) > hl.braking_distance(V, hl.SERVICE_DECEL)
def test_braking_split_sums():
    br = hl.braking_report()
    assert abs(br["recovered_kwh"] + br["eddy_heat_kwh"] - br["kinetic_energy_kwh"]) < 0.2
def test_block_spacing_exceeds_eddy_stop():
    assert hl.block_spacing(V)["block_spacing_m"] > hl.braking_distance(V, hl.EDDY_DECEL)
def test_capacity_positive(): assert hl.line_capacity(V) > 0
def test_braking_gate(): assert hl.braking_report()["gate"] == "HOLD"

# --- thermal
def test_radiator_flux_zero_at_equal_temps(): assert hl.radiator_flux_w_m2(300.0, 300.0) == 0.0
def test_radiator_flux_positive(): assert hl.radiator_flux_w_m2() > 0
def test_radiator_area_formula():
    assert abs(hl.radiator_area_m2(10.0) - 10000.0 / hl.radiator_flux_w_m2()) < 1e-9
def test_radiator_fits_skin(): assert hl.radiator_area_m2() < hl.pod_skin_area_m2()
def test_pcm_buffer_formula():
    assert abs(hl.pcm_buffer_mass_kg(10.0, 30.0) - 10.0 * 30.0 * 60.0 / hl.PCM_LATENT_KJ_KG) < 1e-9
def test_heat_load_sum(): assert abs(hl.total_heat_load_kw() - 10.0) < 1e-9

# --- classifier
def test_classifier_accuracy(): assert hl.regime_report()["training_accuracy"] >= 0.85
def test_classifier_scenarios():
    s = hl.regime_report()["scenarios"]
    assert s["la_sf_design"] == "feasible"
    assert s["regional_300km_500pa"] == "marginal"
    assert s["cross_country_open_air"] == "infeasible"
    assert s["fat_pod_small_tube"] == "infeasible"
def test_design_features():
    f = hl.design_features(560.0, 100.0, 0.36)
    assert abs(f[0] - 5.6) < 1e-12 and abs(f[1] - 2.0) < 1e-12 and abs(f[2] - 3.6) < 1e-12

# --- gates, seats, CLI
def test_hold_gates_14():
    assert len(hl.HOLD_GATES) == 14
    assert all(v.startswith("HOLD") for v in hl.HOLD_GATES.values())
def test_gate_behavior():
    assert hl.gate("live_passenger_operation") == "HOLD"
    assert hl.gate("run_simulation") == "PROCEED"
def test_carbon4_no_override(): assert hl.carbon4_decide()["can_override_hold"] is False
def test_claude_no_override(): assert hl.claude_advisor()["can_override_hold"] is False
def test_flow_plan_only():
    f = hl.google_flow_plan()
    assert f["rendered"] is False and f["live"] == 0
def test_hold_demo_exit_2(): assert hl.main(["hold-demo"]) == 2
def test_hold_demo_ungated_exit_0(): assert hl.main(["hold-demo", "run_simulation"]) == 0
def test_checks_all_pass():
    checks = hl.run_checks()
    assert all(ok for _, ok in checks) and len(checks) >= 70
def test_demo_exit_0(capsys):
    assert hl.main([]) == 0
    out = capsys.readouterr().out
    assert "VERDICT PROCEED" in out and "CHECKS" in out
