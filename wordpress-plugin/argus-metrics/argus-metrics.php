<?php
/**
 * Plugin Name: Argusmetrics
 * Plugin URI: https://argusmetrics.io
 * Description: Privacy-first analytics for your WordPress site. Simple, lightweight, and GDPR-compliant.
 * Version: 1.1.0
 * Author: Argusmetrics
 * Author URI: https://argusmetrics.io
 * License: GPL v2 or later
 * License URI: https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain: argus-metrics
 * Domain Path: /languages
 */

// Exit if accessed directly
if (!defined('ABSPATH')) {
    exit;
}

// Define plugin constants
define('ARGUS_METRICS_VERSION', '1.1.0');
define('ARGUS_METRICS_PLUGIN_DIR', plugin_dir_path(__FILE__));
define('ARGUS_METRICS_PLUGIN_URL', plugin_dir_url(__FILE__));

/**
 * Main Argusmetrics Plugin Class
 */
class Argus_Metrics {

    /**
     * Single instance of the class
     */
    private static $instance = null;

    /**
     * Get instance
     */
    public static function get_instance() {
        if (null === self::$instance) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    /**
     * Constructor
     */
    private function __construct() {
        $this->init_hooks();
    }

    /**
     * Initialize hooks
     */
    private function init_hooks() {
        // Admin hooks
        add_action('admin_menu', array($this, 'add_admin_menu'));
        add_action('admin_init', array($this, 'register_settings'));
        add_action('admin_enqueue_scripts', array($this, 'enqueue_admin_styles'));

        // Frontend hooks
        add_action('wp_head', array($this, 'add_tracking_script'), 1);

        // Plugin links
        add_filter('plugin_action_links_' . plugin_basename(__FILE__), array($this, 'add_settings_link'));
    }

    /**
     * Add admin menu
     */
    public function add_admin_menu() {
        add_options_page(
            __('Argusmetrics Settings', 'argus-metrics'),
            __('Argusmetrics', 'argus-metrics'),
            'manage_options',
            'argus-metrics',
            array($this, 'render_settings_page')
        );
    }

    /**
     * Register settings
     */
    public function register_settings() {
        register_setting('argus_metrics_options', 'argus_metrics_tracking_code', array(
            'type' => 'string',
            'sanitize_callback' => array($this, 'sanitize_tracking_code'),
            'default' => ''
        ));

        register_setting('argus_metrics_options', 'argus_metrics_api_endpoint', array(
            'type' => 'string',
            'sanitize_callback' => 'esc_url_raw',
            'default' => 'https://app.argusmetrics.io/api/v1/analytics/track'
        ));

        register_setting('argus_metrics_options', 'argus_metrics_exclude_outbound', array(
            'type' => 'string',
            'sanitize_callback' => 'sanitize_text_field',
            'default' => ''
        ));

        register_setting('argus_metrics_options', 'argus_metrics_exclude_admins', array(
            'type' => 'boolean',
            'default' => true
        ));
    }

    /**
     * Sanitize tracking code
     */
    public function sanitize_tracking_code($code) {
        $code = sanitize_text_field($code);
        // Tracking codes are 8 characters
        if (strlen($code) !== 8) {
            add_settings_error(
                'argus_metrics_tracking_code',
                'invalid_code',
                __('Tracking code must be exactly 8 characters.', 'argus-metrics')
            );
            return get_option('argus_metrics_tracking_code', '');
        }
        return $code;
    }

    /**
     * Enqueue admin styles
     */
    public function enqueue_admin_styles($hook) {
        if ('settings_page_argus-metrics' !== $hook) {
            return;
        }
        wp_enqueue_style(
            'argus-metrics-admin',
            ARGUS_METRICS_PLUGIN_URL . 'assets/css/admin.css',
            array(),
            ARGUS_METRICS_VERSION
        );
    }

    /**
     * Render settings page
     */
    public function render_settings_page() {
        if (!current_user_can('manage_options')) {
            return;
        }

        $tracking_code = get_option('argus_metrics_tracking_code', '');
        $api_endpoint = get_option('argus_metrics_api_endpoint', 'https://app.argusmetrics.io/api/v1/analytics/track');
        $exclude_outbound = get_option('argus_metrics_exclude_outbound', '');
        $exclude_admins = get_option('argus_metrics_exclude_admins', true);

        include ARGUS_METRICS_PLUGIN_DIR . 'includes/admin-settings.php';
    }

    /**
     * Add tracking script to frontend
     */
    public function add_tracking_script() {
        // Skip if no tracking code
        $tracking_code = get_option('argus_metrics_tracking_code', '');
        if (empty($tracking_code)) {
            return;
        }

        // Skip if user is admin and exclude_admins is enabled
        $exclude_admins = get_option('argus_metrics_exclude_admins', true);
        if ($exclude_admins && current_user_can('manage_options')) {
            echo "<!-- Argusmetrics: Tracking disabled for administrators -->\n";
            return;
        }

        $api_endpoint = get_option('argus_metrics_api_endpoint', 'https://app.argusmetrics.io/api/v1/analytics/track');
        $exclude_outbound = get_option('argus_metrics_exclude_outbound', '');

        // Build script URL
        $script_url = 'https://argusmetrics.io/static/tracker.min.js';

        ?>
<!-- Argusmetrics Analytics -->
<script defer
    data-tracking-code="<?php echo esc_attr($tracking_code); ?>"
    data-api-endpoint="<?php echo esc_attr($api_endpoint); ?>"
    <?php if (!empty($exclude_outbound)) : ?>
    data-exclude-outbound="<?php echo esc_attr($exclude_outbound); ?>"
    <?php endif; ?>
    src="<?php echo esc_url($script_url); ?>">
</script>
<!-- End Argusmetrics -->
        <?php
    }

    /**
     * Add settings link on plugin page
     */
    public function add_settings_link($links) {
        $settings_link = '<a href="' . admin_url('options-general.php?page=argus-metrics') . '">' . __('Settings', 'argus-metrics') . '</a>';
        array_unshift($links, $settings_link);
        return $links;
    }
}

/**
 * Initialize plugin
 */
function argus_metrics_init() {
    return Argus_Metrics::get_instance();
}

// Start the plugin
argus_metrics_init();
