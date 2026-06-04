#!/bin/bash
# Ai assisted script by RBolisay
# --- Initial Warning ---
echo "⚠️ WARNING: Run only on navoff1! ⚠️"
echo "Press Enter to continue or Ctrl+C to abort."
read -r
echo # Add a newline for better readability after user presses Enter
# --- End Initial Warning ---

# Define paths
NGINX_CONF="/etc/nginx/nginx.conf"
MD5CHECK_SCRIPT="/usr/local/trinop/site_scripts/md5check.py"
CRON_JOB="*/1 * * * * /usr/local/trinop/site_scripts/md5check.py" # Assuming python2/3 is correctly linked or script has shebang
RESULTS_URL="http://136.249.XXX.181/md5check_report.html" # Replace XXX with actual IP octet
LOCAL_CSV="/usr/local/trinop/dbase/links/qcfiles/md5sum/md5check.csv"

# Variables to store user input
NAV_P1_DIR_CONFIG=""
OBP_P1_DIR_CONFIG=""
SEQUENCE_RANGES_STR_CONFIG="" # Variable for the new setting

confirm_md5check_script() {
    while [[ ! -f "$MD5CHECK_SCRIPT" ]]; do
        echo "⚠️  ATTENTION: Copy the md5check.py file to /usr/local/trinop/site_scripts before proceeding."
        echo "Make sure it is Python 2.7 compatible if that's your system's default python for cron."
        echo "Press Enter to Continue..."
        read -r
    done
    echo "✔ md5check.py found in /usr/local/trinop/site_scripts. Proceeding..."
}

prompt_configurations() {
    echo "🔹 Please enter the NAV_P1_DIR directory (default: /usr/local/trinop/dbase/links/P111/P111_SSREG):"
    read -r NAV_P1_DIR_INPUT
    NAV_P1_DIR_CONFIG=${NAV_P1_DIR_INPUT:-"/usr/local/trinop/dbase/links/P111/P111_SSREG"}

    echo "🔹 Please enter the OBP_P1_DIR directory (default: /usr/local/trinop/dbase/links/nav2dp/cXXXX/P111_SSREG):"
    echo "   (Note: Replace cXXXX with your actual c-number if applicable)"
    read -r OBP_P1_DIR_INPUT
    OBP_P1_DIR_CONFIG=${OBP_P1_DIR_INPUT:-"/usr/local/trinop/dbase/links/nav2dp/cXXXX/P111_SSREG"}

    echo ""
    echo "🔹 Please enter the Sequence Ranges String."
    echo "   Examples:"
    echo "     '3001-3500, 1001-1500' (process sequences in these two ranges)"
    echo "     '4001, 4005' (process only sequences 4001 and 4005)"
    echo "     Leave empty to auto-detect sequences from min actual file to max actual file (default)."
    read -r SEQUENCE_RANGES_INPUT
    # If user enters nothing, it will be an empty string, which is the default for auto-detect
    SEQUENCE_RANGES_STR_CONFIG=${SEQUENCE_RANGES_INPUT:-""}


    echo "✔ Using NAV_P1_DIR: $NAV_P1_DIR_CONFIG"
    echo "✔ Using OBP_P1_DIR: $OBP_P1_DIR_CONFIG"
    if [[ -z "$SEQUENCE_RANGES_STR_CONFIG" ]]; then
        echo "✔ Using Sequence Ranges: Auto-Detect (empty string)"
    else
        echo "✔ Using Sequence Ranges: '$SEQUENCE_RANGES_STR_CONFIG'"
    fi
}

update_md5check_script() {
    if [[ ! -f "$MD5CHECK_SCRIPT" ]]; then
        echo "❌ md5check.py not found at $MD5CHECK_SCRIPT!"
        exit 1
    fi

    # Escape for sed: handles / & \ and also the ' used in the replacement string itself
    local nav_p1_dir_esc=$(echo "$NAV_P1_DIR_CONFIG" | sed -e 's/[\/&]/\\&/g' -e "s/'/'\\\\''/g")
    local obp_p1_dir_esc=$(echo "$OBP_P1_DIR_CONFIG" | sed -e 's/[\/&]/\\&/g' -e "s/'/'\\\\''/g")
    # For SEQUENCE_RANGES_STR, we need to be careful if it contains quotes or special characters.
    # The replacement will be `SEQUENCE_RANGES_STR = "USER_INPUT"`
    # We need to escape backslashes and double quotes within the USER_INPUT if they exist.
    local sequence_ranges_esc=$(echo "$SEQUENCE_RANGES_STR_CONFIG" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')


    echo "Updating $MD5CHECK_SCRIPT..."
    # Using a temporary file for sed operations to avoid issues with -i on some systems/versions
    local temp_script_file="${MD5CHECK_SCRIPT}.tmp"
    cp "$MD5CHECK_SCRIPT" "$temp_script_file"

    # Update NAV_P1_DIR
    sed "s|^NAV_P1_DIR = .*|NAV_P1_DIR = \"${nav_p1_dir_esc}\"|" "$temp_script_file" > "${temp_script_file}.new" && mv "${temp_script_file}.new" "$temp_script_file"
    # Update OBP_P1_DIR
    sed "s|^OBP_P1_DIR = .*|OBP_P1_DIR = \"${obp_p1_dir_esc}\"|" "$temp_script_file" > "${temp_script_file}.new" && mv "${temp_script_file}.new" "$temp_script_file"
    # Update SEQUENCE_RANGES_STR
    # This assumes the line in md5check.py looks like: SEQUENCE_RANGES_STR = "..." or SEQUENCE_RANGES_STR = ''
    sed "s|^SEQUENCE_RANGES_STR = .*|SEQUENCE_RANGES_STR = \"${sequence_ranges_esc}\"|" "$temp_script_file" > "${temp_script_file}.new" && mv "${temp_script_file}.new" "$temp_script_file"
    
    # Check if sed operations were successful (basic check)
    # Note: This grep check might be too simple if the escaped strings themselves contain complex patterns.
    # For robust checking, one might compare checksums of the file before/after specific sed lines.
    if ! grep -q "NAV_P1_DIR = \"${nav_p1_dir_esc}\"" "$temp_script_file" || \
       ! grep -q "OBP_P1_DIR = \"${obp_p1_dir_esc}\"" "$temp_script_file" || \
       ! grep -q "SEQUENCE_RANGES_STR = \"${sequence_ranges_esc}\"" "$temp_script_file"; then
        echo "❌ Error updating $MD5CHECK_SCRIPT with sed. Check permissions or sed patterns."
        echo "   NAV_P1_DIR expected: NAV_P1_DIR = \"${nav_p1_dir_esc}\""
        echo "   OBP_P1_DIR expected: OBP_P1_DIR = \"${obp_p1_dir_esc}\""
        echo "   SEQUENCE_RANGES_STR expected: SEQUENCE_RANGES_STR = \"${sequence_ranges_esc}\""
        rm "$temp_script_file"
        exit 1
    fi

    mv "$temp_script_file" "$MD5CHECK_SCRIPT"
    echo "✔ Updated md5check.py with new configurations!"
    # Ensure the script is executable
    chmod +x "$MD5CHECK_SCRIPT"
    if [ $? -eq 0 ]; then
        echo "✔ Set execute permissions on $MD5CHECK_SCRIPT."
    else
        echo "⚠️  Warning: Failed to set execute permissions on $MD5CHECK_SCRIPT."
    fi
}


update_nginx_config() {
    echo "Updating Nginx configuration..."
    local nginx_config_updated=false # Flag to track if we made changes

    # Check if the specific location block already exists
    # We're looking for the start of the block.
    # Using grep -Pzo for multi-line pattern matching if available, otherwise simpler grep.
    # Simpler grep for broader compatibility:
    if sudo grep -q "location /md5check_report.html {" "$NGINX_CONF"; then
        echo "✔ Nginx location block for /md5check_report.html already seems to exist. Skipping modification."
        # We could add more sophisticated checks here to see if the existing block is *exactly* what we want.
        # For now, if it exists, we assume it's okay or managed manually.
    else
        echo "Nginx location block for /md5check_report.html not found. Adding it..."
        # Remove any potentially old/malformed `location /md5check_report.html` entries first
        # This ensures we don't just append if a partial or different block exists.
        # Using a different delimiter for sed path to avoid conflict with slashes in path
        # The original sed for removal might be too broad if other similar locations exist.
        # A more precise removal would target the specific block more carefully if needed.
        # For now, assuming the original removal logic is acceptable for cleanup.
        sudo sed -i '\#location /md5check_report.html {#,/^        }#d' "$NGINX_CONF" # Original removal

        # Insert the location block after the first `root /usr/share/nginx/html;` (ignoring spaces)
        sudo sed -i '/^\s*root\s*\/usr\/share\/nginx\/html;/a \
            \n        # Serve md5check_report.html explicitly\
            location /md5check_report.html {\
                root /usr/share/nginx/html;\
                index md5check_report.html;\
                autoindex on;  # Enables browsing directory if needed\
                autoindex_exact_size off;\
                autoindex_localtime on;\
                expires 30s;  # Cache for 30s to avoid constant reloading\
            }' "$NGINX_CONF"
        nginx_config_updated=true
        echo "✔ Nginx configuration updated to add location block."
    fi

    if [ "$nginx_config_updated" = true ]; then
        # Verify the edit
        echo "Verifying changes. Showing relevant part of nginx.conf:"
        grep -A 7 '/md5check_report.html' "$NGINX_CONF" || echo " (Location block not found after update, check nginx.conf manually)"

        # Test the nginx configuration
        echo "Testing Nginx configuration..."
        if sudo nginx -t; then
            echo "✔ Nginx configuration is valid. Restarting Nginx..."
            if sudo systemctl restart nginx; then
                echo "✔ Nginx restarted successfully!"
            else
                echo "❌ Failed to restart Nginx. Check 'sudo systemctl status nginx' and 'sudo journalctl -xe'."
                exit 1
            fi
        else
            echo "❌ Nginx configuration test failed! Not restarting."
            exit 1
        fi
    else
        echo "✔ No changes made to Nginx configuration that require a restart."
    fi
}


add_cron_job() {
    echo "✔ Ensuring md5check.py cron job is installed for the current user..."

    # Get current user's cron jobs and remove old versions of md5check.py
    (crontab -l 2>/dev/null | grep -v 'md5check.py' || true) | crontab -

    # Add the new cron job
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

    echo "✔ Cron job added successfully! You can check it with 'crontab -l'"
}

ensure_cron_running() {
    echo "✔ Checking if crond service is running..."
    if systemctl is-active --quiet crond; then
        echo "✔ Cron service is running."
    else
        echo "❌ Cron service is not running. Starting it now..."
        sudo systemctl start crond
        sudo systemctl enable crond
        echo "✔ Cron service started and enabled."
    fi
}

# --- Main script execution ---
# Warning is now handled at the very top
confirm_md5check_script
prompt_configurations 
update_md5check_script
update_nginx_config
add_cron_job
ensure_cron_running

echo ""
echo "🚀 Installation complete! MD5 Check script will now run every minute."
echo ""
echo "📢 **MD5 Check Results**:"
echo "🌐 View the report at: $RESULTS_URL"
echo "📂 Results also saved locally at: $LOCAL_CSV"
