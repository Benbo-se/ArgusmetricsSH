<?php
/**
 * Argusmetrics Uninstall
 *
 * Clean up plugin data when plugin is deleted (not just deactivated)
 */

// If uninstall not called from WordPress, exit
if (!defined('WP_UNINSTALL_PLUGIN')) {
    exit;
}

// Delete plugin options
delete_option('argus_metrics_tracking_code');
delete_option('argus_metrics_api_endpoint');
delete_option('argus_metrics_exclude_outbound');
delete_option('argus_metrics_exclude_admins');

// For multisite installations
if (is_multisite()) {
    global $wpdb;
    $blog_ids = $wpdb->get_col("SELECT blog_id FROM $wpdb->blogs");

    foreach ($blog_ids as $blog_id) {
        switch_to_blog($blog_id);

        delete_option('argus_metrics_tracking_code');
        delete_option('argus_metrics_api_endpoint');
        delete_option('argus_metrics_exclude_outbound');
        delete_option('argus_metrics_exclude_admins');

        restore_current_blog();
    }
}
