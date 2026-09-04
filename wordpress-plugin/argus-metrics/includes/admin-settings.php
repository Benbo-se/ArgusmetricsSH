<?php
/**
 * Admin Settings Page Template
 */

// Exit if accessed directly
if (!defined('ABSPATH')) {
    exit;
}
?>

<div class="wrap argus-metrics-settings">
    <h1><?php echo esc_html(get_admin_page_title()); ?></h1>

    <?php settings_errors('argus_metrics_tracking_code'); ?>

    <div class="argus-metrics-container">
        <div class="argus-metrics-main">
            <form method="post" action="options.php">
                <?php
                settings_fields('argus_metrics_options');
                ?>

                <table class="form-table" role="presentation">
                    <tbody>
                        <!-- Tracking Code -->
                        <tr>
                            <th scope="row">
                                <label for="argus_metrics_tracking_code">
                                    <?php _e('Tracking Code', 'argus-metrics'); ?>
                                    <span class="required">*</span>
                                </label>
                            </th>
                            <td>
                                <input
                                    type="text"
                                    id="argus_metrics_tracking_code"
                                    name="argus_metrics_tracking_code"
                                    value="<?php echo esc_attr($tracking_code); ?>"
                                    class="regular-text code"
                                    placeholder="a1b2c3d4"
                                    maxlength="8"
                                    pattern="[a-zA-Z0-9]{8}"
                                    required
                                />
                                <p class="description">
                                    <?php _e('Enter your 8-character tracking code from Argusmetrics.', 'argus-metrics'); ?>
                                    <br>
                                    <?php
                                    _e('Get it from your own Argusmetrics instance, after adding this website there.', 'argus-metrics');
                                    ?>
                                </p>
                                <?php if (!empty($tracking_code)) : ?>
                                    <p class="argus-status-active">
                                        ✓ <?php _e('Tracking is active', 'argus-metrics'); ?>
                                    </p>
                                <?php else : ?>
                                    <p class="argus-status-inactive">
                                        ⚠ <?php _e('Tracking is not configured', 'argus-metrics'); ?>
                                    </p>
                                <?php endif; ?>
                            </td>
                        </tr>

                        <!-- Instance URL -->
                        <tr>
                            <th scope="row">
                                <label for="argus_metrics_instance_url">
                                    <?php _e('Instance URL', 'argus-metrics'); ?>
                                </label>
                            </th>
                            <td>
                                <input
                                    type="url"
                                    id="argus_metrics_instance_url"
                                    name="argus_metrics_instance_url"
                                    value="<?php echo esc_attr($instance_url); ?>"
                                    class="regular-text code"
                                    placeholder="https://analytics.your-domain.com"
                                    required
                                />
                                <p class="description">
                                    <?php _e('The address of the Argusmetrics you run. Argusmetrics is self-hosted only, so there is no default and nothing is tracked until this is set. The tracking script and the API are both taken from here.', 'argus-metrics'); ?>
                                </p>
                            </td>
                        </tr>

                        <!-- Exclude Outbound Domains -->
                        <tr>
                            <th scope="row">
                                <label for="argus_metrics_exclude_outbound">
                                    <?php _e('Exclude Outbound Domains', 'argus-metrics'); ?>
                                </label>
                            </th>
                            <td>
                                <input
                                    type="text"
                                    id="argus_metrics_exclude_outbound"
                                    name="argus_metrics_exclude_outbound"
                                    value="<?php echo esc_attr($exclude_outbound); ?>"
                                    class="regular-text"
                                    placeholder="example.com, another.com"
                                />
                                <p class="description">
                                    <?php _e('Comma-separated list of domains to exclude from outbound link tracking.', 'argus-metrics'); ?>
                                </p>
                            </td>
                        </tr>

                        <!-- Exclude Admins -->
                        <tr>
                            <th scope="row">
                                <?php _e('Exclude Administrators', 'argus-metrics'); ?>
                            </th>
                            <td>
                                <fieldset>
                                    <label>
                                        <input
                                            type="checkbox"
                                            name="argus_metrics_exclude_admins"
                                            value="1"
                                            <?php checked($exclude_admins, true); ?>
                                        />
                                        <?php _e('Do not track logged-in administrators', 'argus-metrics'); ?>
                                    </label>
                                    <p class="description">
                                        <?php _e('Recommended to keep enabled to get accurate visitor statistics.', 'argus-metrics'); ?>
                                    </p>
                                </fieldset>
                            </td>
                        </tr>
                    </tbody>
                </table>

                <?php submit_button(__('Save Settings', 'argus-metrics')); ?>
            </form>
        </div>

        <div class="argus-metrics-sidebar">
            <!-- Quick Start -->
            <div class="argus-card">
                <h2><?php _e('Quick Start', 'argus-metrics'); ?></h2>
                <ol>
                    <li><?php _e('Run an Argusmetrics instance of your own. See', 'argus-metrics'); ?> <a href="https://github.com/Benbo-se/ArgusmetricsSH" target="_blank">the repository</a>.</li>
                    <li><?php _e('Add your website and get your tracking code', 'argus-metrics'); ?></li>
                    <li><?php _e('Enter the tracking code above', 'argus-metrics'); ?></li>
                    <li><?php _e('Save settings and start tracking!', 'argus-metrics'); ?></li>
                </ol>
            </div>

            <!-- Features -->
            <div class="argus-card">
                <h2><?php _e('Features', 'argus-metrics'); ?></h2>
                <ul class="argus-feature-list">
                    <li>✓ <?php _e('Privacy-first analytics', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('GDPR compliant', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('No cookies required', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('Lightweight script (&lt;5KB)', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('Real-time analytics', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('Outbound link tracking', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('File download tracking', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('Custom event tracking', 'argus-metrics'); ?></li>
                    <li>✓ <?php _e('Scroll depth tracking', 'argus-metrics'); ?></li>
                </ul>
            </div>

            <!-- Support -->
            <div class="argus-card">
                <h2><?php _e('Need Help?', 'argus-metrics'); ?></h2>
                <p>
                    <a href="https://github.com/Benbo-se/ArgusmetricsSH" target="_blank">
                        <?php _e('Documentation', 'argus-metrics'); ?>
                    </a>
                </p>
                <p>
                    <a href="https://github.com/Benbo-se/ArgusmetricsSH/issues" target="_blank">
                        <?php _e('Support', 'argus-metrics'); ?>
                    </a>
                </p>
            </div>

            <!-- Installation Code -->
            <?php if (!empty($tracking_code)) : ?>
            <div class="argus-card">
                <h2><?php _e('Manual Installation', 'argus-metrics'); ?></h2>
                <p class="description">
                    <?php _e('For non-WordPress sites, use this code:', 'argus-metrics'); ?>
                </p>
                <textarea readonly class="argus-code" rows="6" onclick="this.select()">
<script defer
  data-tracking-code="<?php echo esc_attr($tracking_code); ?>"
  src="https://analytics.your-domain.com/static/tracker.min.js">
</script></textarea>
                <button type="button" class="button" onclick="navigator.clipboard.writeText(this.previousElementSibling.value)">
                    <?php _e('Copy Code', 'argus-metrics'); ?>
                </button>
            </div>
            <?php endif; ?>
        </div>
    </div>
</div>
